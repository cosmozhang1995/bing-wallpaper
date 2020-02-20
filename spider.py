import sys
import os
import oss2
import requests
import json
from configparser import ConfigParser
import logging

# detect the current directory
currdir = os.path.realpath(os.path.dirname(__file__))

# get configuration
config = ConfigParser()
config.read(os.path.join(currdir, "config.conf"))
use_history = config.getboolean("behavior", "history")
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

# print start log
logger.info("Task started.")

# get history list
history = []
if use_history and os.path.isfile(os.path.join(currdir, ".history")):
    with open(os.path.join(currdir, ".history"), "r") as f:
        history = [line.strip() for line in f.readlines()]

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

def append_history(hshid):
    if use_history:
        history.append(hshid)
        with open(os.path.join(currdir, ".history"), "w") as f:
            f.write("\n".join(history))

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

# upload the images
for i in range(len(images)):
    imageitem = images[i]
    if "hsh" not in imageitem: continue
    hshid = imageitem["hsh"]
    if use_history and hshid in history: continue
    if "startdate" not in imageitem: continue
    filename = desc_date_str(imageitem["startdate"]) + "-" + hshid
    # search if image exists
    imagefileprefix = "image/" + filename
    file_exist = True
    try:
        next(oss2.ObjectIterator(bucket, prefix=imagefileprefix))
    except StopIteration as err:
        file_exist = False
    except:
        sys.stderr.write("[WARN] Failed to detect file %s\n" % imagefileprefix)
        continue
    if file_exist:
        append_history(hshid)
        continue
    # set item_status
    item_status[i] = STATUS_FAILED
    # upload the info file
    infofilename = "info/%s.json" % filename
    sys.stdout.write("uploading %s ..." % infofilename)
    result = bucket.put_object(infofilename, json.dumps(imageitem))
    if result.status != 200:
        sys.stderr.write("[WARN] Failed to upload info file for %s\n" % hshid)
        sys.stdout.write("Error.\n")
        logger.warning("Upload %s FAILED." % infofilename)
        continue
    sys.stdout.write("OK.\n")
    logger.info("Upload %s SUCCESS." % infofilename)
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
        sys.stderr.write("[WARN] Image %s has unknown MIME type\n" % hshid)
        sys.stdout.write("Error.\n")
        logger.warning("Image %s has unknown MIME type." % hshid)
        continue
    mimetype = response.headers["Content-Type"]
    if mimetype not in mime2suffix:
        sys.stderr.write("[WARN] Image %s has unknown MIME type \"%s\"\n" % (hshid, mimetype))
        sys.stdout.write("Error.\n")
        logger.warning("Image %s has unknown MIME type \"%s\"." % (hshid, mimetype))
        continue
    sys.stdout.write("OK.\n")
    suffix = mime2suffix[mimetype]
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
    append_history(hshid)
    # set item_status
    item_status[i] = STATUS_SUCCESS

# print complete log
logger.info("Task done: %d successful, %d failed, %d skipped." % (
    len(list(filter(lambda s: s == STATUS_SUCCESS, item_status))),
    len(list(filter(lambda s: s == STATUS_FAILED, item_status))),
    len(list(filter(lambda s: s == STATUS_SKIPPED, item_status)))
))
