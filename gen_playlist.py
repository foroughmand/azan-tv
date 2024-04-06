#!/usr/bin/env python

'''
--------------------- Copyright Block ----------------------

praytimes.py: Prayer Times Calculator (ver 2.3)
Copyright (C) 2007-2011 PrayTimes.org

Python Code: Saleem Shafi, Hamid Zarrabi-Zadeh
Original js Code: Hamid Zarrabi-Zadeh

License: GNU LGPL v3.0

TERMS OF USE:
    Permission is granted to use this code, with or
    without modification, in any website or application
    provided that credit is given to the original work
    with a link back to PrayTimes.org.

This program is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY.

PLEASE DO NOT REMOVE THIS COPYRIGHT BLOCK.

'''

import json, urllib.request
from datetime import date
import argparse
import datetime

import math
import re
import ffmpeg
import zoneinfo
import numpy as np
import sys
import pandas as pd
from pytz import country_timezones, timezone
import requests
import urllib.parse
from geopy.geocoders import Nominatim
from tzfpy import get_tz, get_tzs
import os

#----------------------- PrayTimes Class ------------------------

class PrayTimes():


    #------------------------ Constants --------------------------

    # Time Names
    timeNames = {
        'imsak'    : 'Imsak',
        'fajr'     : 'Fajr',
        'sunrise'  : 'Sunrise',
        'dhuhr'    : 'Dhuhr',
        'asr'      : 'Asr',
        'sunset'   : 'Sunset',
        'maghrib'  : 'Maghrib',
        'isha'     : 'Isha',
        'midnight' : 'Midnight'
    }

    # Calculation Methods
    methods = {
        'MWL': {
            'name': 'Muslim World League',
            'params': { 'fajr': 18, 'isha': 17 } },
        'ISNA': {
            'name': 'Islamic Society of North America (ISNA)',
            'params': { 'fajr': 15, 'isha': 15 } },
        'Egypt': {
            'name': 'Egyptian General Authority of Survey',
            'params': { 'fajr': 19.5, 'isha': 17.5 } },
        'Makkah': {
            'name': 'Umm Al-Qura University, Makkah',
            'params': { 'fajr': 18.5, 'isha': '90 min' } },  # fajr was 19 degrees before 1430 hijri
        'Karachi': {
            'name': 'University of Islamic Sciences, Karachi',
            'params': { 'fajr': 18, 'isha': 18 } },
        'Tehran': {
            'name': 'Institute of Geophysics, University of Tehran',
            'params': { 'fajr': 17.7, 'isha': 14, 'maghrib': 4.5, 'midnight': 'Jafari' } },  # isha is not explicitly specified in this method
        'Jafari': {
            'name': 'Shia Ithna-Ashari, Leva Institute, Qum',
            'params': { 'fajr': 16, 'isha': 14, 'maghrib': 4, 'midnight': 'Jafari' } }
    }

    # Default Parameters in Calculation Methods
    defaultParams = {
        'maghrib': '0 min', 'midnight': 'Standard'
    }

    
    #---------------------- Default Settings --------------------

    calcMethod = 'MWL'
    
    # do not change anything here; use adjust method instead
    settings = {
        "imsak"    : '10 min',
        "dhuhr"    : '0 min',
        "asr"      : 'Standard',
        "highLats" : 'NightMiddle'
    }
    
    timeFormat = '24h'
    timeSuffixes = ['am', 'pm']
    invalidTime =  '-----'

    numIterations = 1
    offset = {}


    #---------------------- Initialization -----------------------

    def __init__(self, method = "MWL") :

        # set methods defaults
        for method, config in self.methods.items():
            for name, value in self.defaultParams.items():
                if not name in config['params'] or config['params'][name] is None:
                    config['params'][name] = value

        # initialize settings
        self.calcMethod = method if method in self.methods else 'MWL'
        params = self.methods[self.calcMethod]['params']
        for name, value in params.items():
            self.settings[name] = value

        # init time offsets
        for name in self.timeNames:
            self.offset[name] = 0


    #-------------------- Interface Functions --------------------

    def setMethod(self, method):
        if method in self.methods:
            self.adjust(self.methods[method].params)
            self.calcMethod = method

    def adjust(self, params):
        self.settings.update(params)

    def tune(self, timeOffsets):
        self.offsets.update(timeOffsets)
            
    def getMethod(self):
        return self.calcMethod

    def getSettings(self):
        return self.settings
        
    def getOffsets(self):
        return self.offset

    def getDefaults(self):
        return self.methods

    # return prayer times for a given date
    def getTimes(self, date, coords, timezone, dst = 0, format = None):
        self.lat = coords[0]
        self.lng = coords[1]
        self.elv = coords[2] if len(coords)>2 else 0
        if format != None:
            self.timeFormat = format
        if type(date).__name__ == 'date':
            date = (date.year, date.month, date.day)
        self.timeZone = timezone + (1 if dst else 0)
        self.jDate = self.julian(date[0], date[1], date[2]) - self.lng / (15 * 24.0)
        return self.computeTimes()
    
    # convert float time to the given format (see timeFormats)
    def getFormattedTime(self, time, format, suffixes = None):
        if math.isnan(time):
            return self.invalidTime
        if format == 'Float':
            return time
        if suffixes == None:
            suffixes = self.timeSuffixes

        time = self.fixhour(time+ 0.5/ 60)  # add 0.5 minutes to round
        hours = math.floor(time)
        
        minutes = math.floor((time- hours)* 60)
        suffix = suffixes[ 0 if hours < 12 else 1 ] if format == '12h' else ''
        formattedTime = "%02d:%02d" % (hours, minutes) if format == "24h" else "%d:%02d" % ((hours+11)%12+1, minutes)
        return formattedTime + suffix

    
    #---------------------- Calculation Functions -----------------------

    # compute mid-day time
    def midDay(self, time):
        eqt = self.sunPosition(self.jDate + time)[1]
        return self.fixhour(12 - eqt)

    # compute the time at which sun reaches a specific angle below horizon 
    def sunAngleTime(self, angle, time, direction = None):
        try:
            decl = self.sunPosition(self.jDate + time)[0]
            noon = self.midDay(time)
            t = 1/15.0* self.arccos((-self.sin(angle)- self.sin(decl)* self.sin(self.lat))/
                    (self.cos(decl)* self.cos(self.lat)))
            return noon+ (-t if direction == 'ccw' else t)
        except ValueError:
            return float('nan')

    # compute asr time
    def asrTime(self, factor, time): 
        decl = self.sunPosition(self.jDate + time)[0]
        angle = -self.arccot(factor + self.tan(abs(self.lat - decl)))
        return self.sunAngleTime(angle, time)

    # compute declination angle of sun and equation of time
    # Ref: http://aa.usno.navy.mil/faq/docs/SunApprox.php
    def sunPosition(self, jd):
        D = jd - 2451545.0
        g = self.fixangle(357.529 + 0.98560028* D)
        q = self.fixangle(280.459 + 0.98564736* D)
        L = self.fixangle(q + 1.915* self.sin(g) + 0.020* self.sin(2*g))

        R = 1.00014 - 0.01671*self.cos(g) - 0.00014*self.cos(2*g)
        e = 23.439 - 0.00000036* D

        RA = self.arctan2(self.cos(e)* self.sin(L), self.cos(L))/ 15.0
        eqt = q/15.0 - self.fixhour(RA)
        decl = self.arcsin(self.sin(e)* self.sin(L))

        return (decl, eqt)
        
    # convert Gregorian date to Julian day
    # Ref: Astronomical Algorithms by Jean Meeus
    def julian(self, year, month, day):
        if month <= 2:
            year -= 1
            month += 12
        A = math.floor(year / 100)
        B = 2 - A + math.floor(A / 4)
        return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + B - 1524.5



    #---------------------- Compute Prayer Times -----------------------

    # compute prayer times at given julian date
    def computePrayerTimes(self, times):
        times = self.dayPortion(times)
        params = self.settings
        
        imsak   = self.sunAngleTime(self.eval(params['imsak']), times['imsak'], 'ccw')
        fajr    = self.sunAngleTime(self.eval(params['fajr']), times['fajr'], 'ccw')
        sunrise = self.sunAngleTime(self.riseSetAngle(self.elv), times['sunrise'], 'ccw')
        dhuhr   = self.midDay(times['dhuhr'])
        asr     = self.asrTime(self.asrFactor(params['asr']), times['asr'])
        sunset  = self.sunAngleTime(self.riseSetAngle(self.elv), times['sunset'])
        maghrib = self.sunAngleTime(self.eval(params['maghrib']), times['maghrib'])
        isha    = self.sunAngleTime(self.eval(params['isha']), times['isha']) 
        return {
            'imsak': imsak, 'fajr': fajr, 'sunrise': sunrise, 'dhuhr': dhuhr,
            'asr': asr, 'sunset': sunset, 'maghrib': maghrib, 'isha': isha
        }

    # compute prayer times
    def computeTimes(self):
        times = {
            'imsak': 5, 'fajr': 5, 'sunrise': 6, 'dhuhr': 12,
            'asr': 13, 'sunset': 18, 'maghrib': 18, 'isha': 18
        }
        # main iterations
        for i in range(self.numIterations):
            times = self.computePrayerTimes(times)
        times = self.adjustTimes(times)
        # add midnight time
        if self.settings['midnight'] == 'Jafari':
            times['midnight'] = times['sunset'] + self.timeDiff(times['sunset'], times['fajr']) / 2
        else:
            times['midnight'] = times['sunset'] + self.timeDiff(times['sunset'], times['sunrise']) / 2

        times = self.tuneTimes(times)
        return self.modifyFormats(times)
        
    # adjust times in a prayer time array
    def adjustTimes(self, times):
        params = self.settings
        tzAdjust = self.timeZone - self.lng / 15.0
        for t,v in times.items():
            times[t] += tzAdjust

        if params['highLats'] != 'None':
            times = self.adjustHighLats(times)

        if self.isMin(params['imsak']):
            times['imsak'] = times['fajr'] - self.eval(params['imsak']) / 60.0
        # need to ask about 'min' settings
        if self.isMin(params['maghrib']):
            times['maghrib'] = times['sunset'] - self.eval(params['maghrib']) / 60.0

        if self.isMin(params['isha']):
            times['isha'] = times['maghrib'] - self.eval(params['isha']) / 60.0
        times['dhuhr'] += self.eval(params['dhuhr']) / 60.0

        return times

    # get asr shadow factor
    def asrFactor(self, asrParam):
        methods = {'Standard': 1, 'Hanafi': 2}
        return methods[asrParam] if asrParam in methods else self.eval(asrParam)

    # return sun angle for sunset/sunrise
    def riseSetAngle(self, elevation = 0):
        elevation = 0 if elevation == None else elevation
        return 0.833 + 0.0347 * math.sqrt(elevation) # an approximation

    # apply offsets to the times
    def tuneTimes(self, times):
        for name, value in times.items():
            times[name] += self.offset[name] / 60.0
        return times

    # convert times to given time format
    def modifyFormats(self, times):
        for name, value in times.items():
            times[name] = self.getFormattedTime(times[name], self.timeFormat)
        return times
    
    # adjust times for locations in higher latitudes
    def adjustHighLats(self, times):
        params = self.settings
        nightTime = self.timeDiff(times['sunset'], times['sunrise']) # sunset to sunrise
        times['imsak'] = self.adjustHLTime(times['imsak'], times['sunrise'], self.eval(params['imsak']), nightTime, 'ccw')
        times['fajr']  = self.adjustHLTime(times['fajr'], times['sunrise'], self.eval(params['fajr']), nightTime, 'ccw')
        times['isha']  = self.adjustHLTime(times['isha'], times['sunset'], self.eval(params['isha']), nightTime)
        times['maghrib'] = self.adjustHLTime(times['maghrib'], times['sunset'], self.eval(params['maghrib']), nightTime)
        return times

    # adjust a time for higher latitudes
    def adjustHLTime(self, time, base, angle, night, direction = None):
        portion = self.nightPortion(angle, night)
        diff = self.timeDiff(time, base) if direction == 'ccw' else self.timeDiff(base, time)
        if math.isnan(time) or diff > portion:
            time = base + (-portion if direction == 'ccw' else portion)
        return time

    # the night portion used for adjusting times in higher latitudes
    def nightPortion(self, angle, night):
        method = self.settings['highLats']
        portion = 1/2.0  # midnight
        if method == 'AngleBased':
            portion = 1/60.0 * angle
        if method == 'OneSeventh':
            portion = 1/7.0
        return portion * night

    # convert hours to day portions
    def dayPortion(self, times):
        for i in times:
            times[i] /= 24.0
        return times

    
    #---------------------- Misc Functions -----------------------

    # compute the difference between two times
    def timeDiff(self, time1, time2):
        return self.fixhour(time2- time1)

    # convert given string into a number
    def eval(self, st):
        val = re.split('[^0-9.+-]', str(st), 1)[0]
        return float(val) if val else 0

    # detect if input contains 'min'
    def isMin(self, arg):
        return isinstance(arg, str) and arg.find('min') > -1


    #----------------- Degree-Based Math Functions -------------------

    def sin(self, d): return math.sin(math.radians(d))
    def cos(self, d): return math.cos(math.radians(d))
    def tan(self, d): return math.tan(math.radians(d))

    def arcsin(self, x): return math.degrees(math.asin(x))
    def arccos(self, x): return math.degrees(math.acos(x))
    def arctan(self, x): return math.degrees(math.atan(x))

    def arccot(self, x): return math.degrees(math.atan(1.0/x))
    def arctan2(self, y, x): return math.degrees(math.atan2(y, x))

    def fixangle(self, angle): return self.fix(angle, 360.0)
    def fixhour(self, hour): return self.fix(hour, 24.0)

    def fix(self, a, mode):
        if math.isnan(a):
            return a
        a = a - mode * (math.floor(a / mode))
        return a + mode if a < 0 else a


#---------------------- prayTimes Object -----------------------

prayTimes = PrayTimes(method="Tehran")


def get_owghat(d: date, timezone_name: str = 'CET', location_latlonelev = (52.2689, 10.5268, 75.0/1000)):
    time_zone = zoneinfo.ZoneInfo(timezone_name)
    dst_date = datetime.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=time_zone)
    # dst = 1 if dst_date.dst().seconds > 0 else 0
    dst = time_zone.utcoffset(dst_date).seconds/3600
    # print(f'dst={dst}', file=sys.stderr)
    times = prayTimes.getTimes(d, location_latlonelev, dst, format = '24h')
    print(f'times={times} dst={dst_date.dst()}', file=sys.stderr)
    times = prayTimes.getTimes(d, location_latlonelev, dst, format = 'Float')
    return times

def get_video_duration(fn):
    info = ffmpeg.probe(fn)
    # print(f'd: {info["format"]["duration"]}', file=sys.stderr)
    return float(info['format']['duration'])

def f_to_hms(x):
    return str(datetime.timedelta(seconds=x))[:-3]

def apply_replacements(lst: list[str], replacements: dict[str, str]):
    r = []
    for l in lst:
        rl = l
        for a, b in replacements.items():
            if rl.find(a):
                rl = rl.replace(a, b)

        for ext in ['', '.mkv', '.mp4', '.m4v', '.webm']:
            if os.path.isfile(rl + ext):
                rl = rl + ext
                break
        if not os.path.isfile(rl):
            raise RuntimeError(f"File '{rl}' with non of the extensions exists.")
        r.append(rl)
    print(f"File names: {r}", file=sys.stderr)
    return r

def gen(azan_times, program, timer_file, replacements):
    print(f"gen {program} timer_file:{timer_file}", file=sys.stderr)
    timer_file = apply_replacements([timer_file], replacements)[0]
    timer_duration = get_video_duration(timer_file)
    r = []

    filled = 0
    for p in program:
        print(f"Program {p}", file=sys.stderr)
        name = p['name']
        p['pre'] = apply_replacements(p['pre'], replacements)
        p['post'] = apply_replacements(p['post'], replacements)
        pre_durations = np.array([get_video_duration(f) for f in p['pre']])
        post_durations = np.array([get_video_duration(f) for f in p['post']])
    
        start = azan_times[name] - pre_durations.sum()
    
        r.append((filled, start, timer_duration, timer_file))
        pre_info = [(0, d, d, f) for f, d, x in zip(p['pre'], pre_durations, [0] + pre_durations.cumsum().tolist()[:-1])]
        r.extend(pre_info)
        post_info = [(0, d, d, f) for f, d, x in zip(p['post'], post_durations, [0] + post_durations.cumsum().tolist()[:-1])]
        r.extend(post_info)

        # print(f"fill: {filled} pre:{pre_info} post:{post_info}", file=sys.stderr)
        print(f"fill: {filled}[{f_to_hms(filled)}] pre:{pre_durations.sum()}[{f_to_hms(pre_durations.sum())}] post:{post_durations.sum()} azan_time:{azan_times[name]}[{f_to_hms(azan_times[name])}] start:{start}[{f_to_hms(start)}]", file=sys.stderr)

        filled = start + pre_durations.sum() + post_durations.sum()

    r.append((filled, 24*3600, timer_duration, timer_file))
    # r.append((0, 24*3600, timer_duration, timer_file))

    print(f"len={np.array([o - i for i, o, d, f in r]).sum()}", file=sys.stderr)
    return r

def gen_text(channel, d, program):
    j = {"channel": channel,
         "date": d,
         "program": [{"in": st, "out": en, "duration": d, "source": f} for st, en, d, f in program]}
    # print(j, file=sys.stderr)
    return json.dumps(j)
    

# Define a custom argument type for a list of strings
def list_of_strings(arg):
    return arg.split(':')

def find_city(query):
    r = []
    for country, cities in country_timezones.items():
        for city in cities:
            if query in city:
                r.append(timezone(city))
    return r

# conf = pd.read_json(args.conf, lines=True)

def main(argv):
    argv = [x if type(x) is str else str(x) for x in argv]
    # print("gen_playlist", argv)
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='date')
    parser.add_argument('--conf', help='config file')
    parser.add_argument('--azan', help='sets azan times for debug')
    parser.add_argument('--city', default='Braunschweig', help='City name')
    parser.add_argument('--city_aviny', default='2130', help='City id in aviny website')
    parser.add_argument('--source', default='aviny:izhamburg', help='A colon separated list of sources to be included in calculation. Items are "prayertimes", "avini", "izhamburg".')
    parser.add_argument('--times', help='Calculated times are saving into this file.')
    parser.add_argument('--out', default='-', help='File for saving the program to. "-" for standard output.')
    parser.add_argument('--replacements', help='replacement file')
    args = parser.parse_args(args=argv)

    with open(args.conf) as json_file:
        conf = json.load(json_file)

    replacements = {}
    if args.replacements:
        with open(args.replacements) as f:
            replacements = json.load(f)

    azan = 0

    if args.azan is not None:
        # for debug
        azan = {}
        for ot in args.azan.split(','):
            ots = ot.split(':')
            x = ots[1:]
            azan[ots[0]] = int(x[0]) * 3600 + int(x[1]) * 60 + (int(x[2]) if len(x) >= 3 else 0)
    else:
        address = args.city
        date = datetime.datetime.strptime(args.date, '%Y-%m-%d').date()

        geolocator = Nominatim(user_agent="azan_id")
        location = geolocator.geocode(address)
        country = location.address.split(', ')[-1]
        # print(location.address)
        # print((location.latitude, location.longitude))
        # if len(find_city(args.city)) != 1:
        #     raise RuntimeError(f"City is ambigous {args.city}: {find_city(args.city)}")
        # url = 'https://nominatim.openstreetmap.org/search?q=' + urllib.parse.quote(args.city) +'?format=json'
        # response = requests.get(url).json()
        # print(response, file=sys.stderr)
        tz = get_tz(location.longitude, location.latitude)

        # print(f"city={args.city} tz={tz} location={location} l={location.latitude},{location.longitude}", file=sys.stderr)

        # print(get_owghat(datetime.datetime.strptime(args.date, '%Y-%m-%d').date()), file=sys.stderr)
        owghat = get_owghat(date, timezone_name=tz, location_latlonelev=(location.latitude, location.longitude, location.altitude/1000))
        azan_prayertimes = {o:t*3600 for o,t in owghat.items()}
        print('PrayerTimes', azan_prayertimes, file=sys.stderr)

        url = f'https://prayer.aviny.com/api/prayertimes/{args.city_aviny}'
        r = requests.get(url).json()
        azan_r = {'imsak': r['Imsaak'], 'fajr': r['Imsaak'], 'sunrise': r['Sunrise'], 
                'dhuhr': r['Noon'], 'asr': r['Noon'], 'sunset': r['Sunset'], 
                'maghrib': r['Maghreb'], 'isha': r['Maghreb'], 'midnight': r['Midnight']}
        # print(azan_r, file=sys.stderr)
        # print({o:[int(i) for i in t.split(':')] for o, t in azan_r.items()}, file=sys.stderr)
        azan_aviny = {o:(t[0]*3600+t[1]*60+t[2]) for o, t in {o:[int(i) for i in t.split(':')] for o, t in azan_r.items()}.items()}
        print('Aviny', azan_aviny, file=sys.stderr)

        date_yb = datetime.date(date.year, 1, 1)
        url = f'https://syber.ir/api/oghat/oneday/{location.latitude}/{location.longitude}/{(date - date_yb).days}/{date.year}/0/'
        r = requests.get(url).json()
        azan_r = {'imsak': r['imsakString'], 'fajr': r['modifiedFajrString'], 'sunrise': r['riseString'], 
                'dhuhr': r['noonString'], 'asr': r['asrString'], 'sunset': r['setString'], 
                'maghrib': r['maghribString'], 'isha': r['modifiedIshaString'], 'midnight': r['midnightString']}
        azan_izhamburg = {o:(t[0]*3600+t[1]*60+0) for o, t in {o:[int(i) for i in t.replace(' ', '').split(':')] for o, t in azan_r.items()}.items()}
        print(f'izhamburg {azan_izhamburg}', file=sys.stderr)

        azan_function = {'imsak': min, 'fajr': max, 'sunrise': min, 
                'dhuhr': max, 'asr': max, 'sunset': min, 
                'maghrib': max, 'isha': max, 'midnight': min}
        
        azan_with_source = {'prayertimes' : azan_prayertimes, 'aviny': azan_aviny, 'izhamburg' : azan_izhamburg}

        azan = {o:azan_function[o](*[azan_with_source[src][o] for src in args.source.split(':')]) for o in list(azan_prayertimes.keys())}
        
    if args.times:
        with open(args.times, 'w') as f:
            print(json.dumps(azan), file=f)

    print('azan {} {}'.format(azan, {o:f_to_hms(v) for o, v in azan.items()}), file=sys.stderr)

    program = gen(azan, conf['program'], conf['timer'], replacements)
    j = gen_text(args.city + " Azan", args.date, program)

    with open(args.out, 'w') if args.out != '-' else sys.stdout as f:
        print(j, file = f)

if __name__ == "__main__":
    main(sys.argv[1:])


    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program.json --azan fajr:06:50:00,dhuhr:12:00:00,maghrib:20:00:00 > playlist4.json
    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program.json > playlist4.json
    # ffplayout -p playlist4.json -o stream --log ffplayout.log -c ffplayout.yml
    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program-hard.json > playlist4.json