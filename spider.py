import sys
import os
import oss2
import requests
import json
from configparser import ConfigParser
import logging
import re
import hashlib

# detect the current directory
currdir = os.path.realpath(os.path.dirname(__file__))

# get configuration
config = ConfigParser()
config.read(os.path.join(currdir, "config.conf"))
use_history = config.getboolean("behavior", "history")
if use_history: max_history = config.getint("behavior", "max_history")
use_log = config.getboolean("log", "enable")
if use_log: log_path = os.path.realpath(os.path.expandvars(config.get("log", "path")))

# initialize logger
logging.basicConfig(filename='/dev/null', filemode='w')
logger = logging.getLogger("spider")
logger.setLevel(level = logging.INFO)
# handler = logging.StreamHandler()
# handler.setLevel(9999)
if use_log:
    handler = logging.FileHandler(log_path)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# notify functions
notify_config = config["notify"] if "notify" in config else {}
notify_format = None
notify_type = "text"
if "format.text" in notify_config:
    notify_format = config.get("notify", "format.text")
    if len(notify_format) >= 2 and ( \
            (notify_format[0] == '"' and notify_format[-1] == '"') or \
            (notify_format[0] == "'" and notify_format[-1] == "'")):
        notify_format = eval(notify_format)
if "format.file" in notify_config:
    notify_format_file = config.get("notify", "format.file")
    if len(notify_format_file) > 0:
        notify_format_file = os.path.realpath(os.path.expandvars(notify_format_file))
        if os.path.isfile(notify_format_file):
            with open(notify_format_file, "r") as f:
                notify_format = f.read()
            if notify_format_file.split(".")[-1].lower() in ["md", "markdown"]:
                notify_type = "markdown"
def notify(**kwargs):
    if notify_format is None or len(notify_format) == 0:
        return
    notify_content = notify_format.format(**kwargs)
    if "dingtalk" in notify_config and config.getboolean("notify", "dingtalk"):
        if notify_type == "markdown":
            msgobj = {
                "msgtype": "markdown",
                "markdown": {
                    "title": re.sub(r"^\#+", "", notify_content.split("\n")[0]).strip(),
                    "text": notify_content
                },
            }
        else:
            msgobj = {
                "msgtype": "text",
                "text": {
                    "content": notify_content
                }
            }
        response = requests.post(
            "https://oapi.dingtalk.com/robot/send?access_token=%s" % config.get("notify", "dingtalk.accessToken"),
            json.dumps(msgobj),
            headers = { "Content-Type": "application/json" }
        )
        print(response.content.decode("utf-8"))
        if response.status_code != 200:
            sys.stderr.write("[WARN] Failed to notify DingTalk\n")
            logger.warning("Failed to notify DingTalk.")
        else:
            response = response.json()
            if response["errcode"] != 0:
                sys.stderr.write("[WARN] Failed to notify DingTalk. Error: %d (%s).\n" % (response["errcode"], response["errmsg"]))
                logger.warning("Failed to notify DingTalk. Error: %d (%s)." % (response["errcode"], response["errmsg"]))


# print start log
logger.info("Task started.")

# get history list
class HistoryItem:
    def __init__(self, hsh=None, sha=None):
        self.hsh = hsh
        self.sha = sha
    def __str__(self):
        return "{}:{}".format(self.hsh or "", self.sha or "")
history = []
if use_history and os.path.isfile(os.path.join(currdir, ".history")):
    with open(os.path.join(currdir, ".history"), "r") as f:
        history = [HistoryItem(*[x.strip() for x in line.strip().split(":")]) for line in f.readlines()]

# request the Bing wallpaper list
response = requests.get("https://cn.bing.com/HPImageArchive.aspx?format=js&idx=0&n=100&ensearch=1&FORM=BEHPTB")
if response.status_code != 200:
    sys.stderr.write("[ERROR] Failed to get the Bing wallpaper list")
    exit(1)
response = response.json()
if "images" not in response:
    sys.stderr.write("[ERROR] Got a unrecognized Bing wallpaper list")
    exit(1)
images = response["images"]

# create the OSS client
auth = oss2.Auth(config.get("oss", "accessKeyId"), config.get("oss", "accessKeySecret"))
bucket = oss2.Bucket(auth, config.get("oss", "endpoint"), config.get("oss", "bucket"))

def find_history(hsh=None, sha=None):
    if hsh is not None:
        return (list(filter(lambda item: item.hsh == hsh, history)) + [None])[0]
    elif sha is not None:
        return (list(filter(lambda item: item.sha == sha, history)) + [None])[0]
    else:
        return None
def append_history(**kwargs):
    if use_history:
        global history
        history.append(HistoryItem(**kwargs))
        history = history[-max_history:]
        with open(os.path.join(currdir, ".history"), "w") as f:
            f.write("\n".join([str(item) for item in history]))

def desc_date_str(datestr):
    newyear = 9999 - int(datestr[0:4])
    newmonth = 12 - int(datestr[4:6])
    newdate = 31 - int(datestr[6:8])
    return "%04d%02d%02d" % (newyear, newmonth, newdate)

mime2suffix = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/bmp": "bmp"
}

STATUS_SKIPPED = 0
STATUS_FAILED = -1
STATUS_SUCCESS = 1
item_status = [STATUS_SKIPPED for item in images]
item_download = [False for item in images]

# upload the images
for i in range(len(images)):
    imageitem = images[i]
    if "hsh" not in imageitem: continue
    hshid = imageitem["hsh"]
    if use_history and find_history(hsh=hshid) is not None: continue
    if "startdate" not in imageitem: continue
    startdate = imageitem["startdate"]
    # set item_status
    item_status[i] = STATUS_FAILED
    # search if image exists
    hsh2sha_filename = "hsh2sha/" + hshid + ".sha256"
    file_exist = True
    try:
        next(oss2.ObjectIterator(bucket, prefix=hsh2sha_filename))
    except StopIteration as err:
        file_exist = False
    except Exception as e:
        import traceback
        sys.stderr.write("[WARN] Failed to detect hsh2sha file %s\n" % hsh2sha_filename)
        continue
    if file_exist:
        append_history(hsh=hshid, sha=None)
        item_status[i] = STATUS_SKIPPED
        continue
    # download the image
    imgurl = "https://cn.bing.com/hpwp/%s" % hshid
    sys.stdout.write("downloading %s ..." % imgurl)
    response = requests.get(imgurl, cookies={'ENSEARCH':'BENVER=1'})
    if response.status_code != 200:
        sys.stdout.write("Failed.\n")
        logger.warning("Download %s FAILED." % imgurl)
        if "url" in imageitem:
            imgurl2 = "https://cn.bing.com" + imageitem["url"]
            sys.stdout.write("downloading %s ..." % imgurl2)
            response = requests.get("https://cn.bing.com" + imageitem["url"], cookies={'ENSEARCH':'BENVER=1'})
            if response.status_code != 200:
                sys.stdout.write("Failed.\n")
                logger.warning("Download %s FAILED." % imgurl2)
            else:
                logger.info("Download %s SUCCESS." % imgurl2)
    else:
        logger.info("Download %s SUCCESS." % imgurl)
    if response.status_code != 200:
        sys.stderr.write("[WARN] Failed to download image %s\n" % hshid)
        continue
    if "Content-Type" not in response.headers:
        sys.stdout.write("Error.\n")
        sys.stderr.write("[WARN] Image %s has unknown MIME type\n" % hshid)
        logger.warning("Image %s has unknown MIME type." % hshid)
        continue
    mimetype = response.headers["Content-Type"]
    if mimetype not in mime2suffix:
        sys.stdout.write("Error.\n")
        sys.stderr.write("[WARN] Image %s has unknown MIME type \"%s\"\n" % (hshid, mimetype))
        logger.warning("Image %s has unknown MIME type \"%s\"." % (hshid, mimetype))
        continue
    sys.stdout.write("OK.\n")
    suffix = mime2suffix[mimetype]
    shahex = hashlib.sha256(response.content).hexdigest()
    filename = desc_date_str(imageitem["startdate"]) + "-" + shahex
    item_download[i] = True
    # search if image exists
    if use_history and find_history(sha=shahex) is not None:
        item_status[i] = STATUS_SKIPPED
        continue
    filename_prefix = "image/" + filename
    file_exist = True
    try:
        next(oss2.ObjectIterator(bucket, prefix=filename_prefix))
    except StopIteration as err:
        file_exist = False
    except:
        sys.stderr.write("[WARN] Failed to detect image file %s\n" % filename_prefix)
        continue
    if file_exist:
        append_history(hsh=hshid, sha=shahex)
        item_status[i] = STATUS_SKIPPED
    else:
        # upload the info file
        infofilename = "info/%s.json" % filename
        sys.stdout.write("uploading %s ..." % infofilename)
        result = bucket.put_object(infofilename, json.dumps(imageitem))
        if result.status != 200:
            sys.stdout.write("Error.\n")
            sys.stderr.write("[WARN] Failed to upload info file for %s\n" % hshid)
            logger.warning("Upload %s FAILED." % infofilename)
            continue
        sys.stdout.write("OK.\n")
        logger.info("Upload %s SUCCESS." % infofilename)
        # upload the image
        imagefilename = "image/%s.%s" % (filename, suffix)
        sys.stdout.write("uploading %s ..." % imagefilename)
        result = bucket.put_object(imagefilename, response.content)
        if result.status != 200:
            sys.stderr.write("[WARN] Failed to upload image %s\n" % hshid)
            sys.stdout.write("Error.\n")
            logger.warning("Upload %s FAILED." % imagefilename)
            continue
        sys.stdout.write("OK.\n")
        logger.info("Upload %s SUCCESS." % imagefilename)
        # append history
        append_history(hsh=hshid, sha=shahex)
        # set item_status
        item_status[i] = STATUS_SUCCESS
    # upload the hsh2sha file
    sys.stdout.write("uploading %s ..." % hsh2sha_filename)
    result = bucket.put_object(hsh2sha_filename, shahex)
    if result.status != 200:
        sys.stdout.write("Error.\n")
        sys.stderr.write("[WARN] Failed to upload hsh2sha file for %s\n" % hshid)
        logger.warning("Upload %s FAILED." % hsh2sha_filename)
        continue
    sys.stdout.write("OK.\n")
    logger.info("Upload %s SUCCESS." % hsh2sha_filename)

# summary
num_success = len(list(filter(lambda s: s == STATUS_SUCCESS, item_status)))
num_failed = len(list(filter(lambda s: s == STATUS_FAILED, item_status)))
num_skipped = len(list(filter(lambda s: s == STATUS_SKIPPED, item_status)))
num_downloaded = len(list(filter(lambda s: s, item_download)))

# print complete log
logger.info("Task done: %d downloaded, %d successful, %d failed, %d skipped." % (num_downloaded, num_success, num_failed, num_skipped))

# notify
notify(success=num_success, failed=num_failed, skipped=num_skipped, downloaded=num_downloaded)
