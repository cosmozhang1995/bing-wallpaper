# Bing Wallpaper Spider

Download all available wallpapers from today's [Bing home page](https://cn.bing.com/?ensearch=1&FORM=BEHPTB). And store them into an OSS engine.

### Get Started

1. `sudo python3 -m pip install -r requirements.txt`.
2. `cp config.example.conf config.conf`, then edit `config.conf` for your configurations.
3. `python3 spider.py`.

### Crontab

Run `crontab -e` to edit your `crontab` file. Append the following line to it:
```
0 12 * * *    python3 /path/to/spider.py
```

As this crontab entry demands, `crontab` will execute the spider on each day's 12:00.
