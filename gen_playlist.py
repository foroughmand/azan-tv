#!/usr/bin/env python


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

"""
PrayTime - Prayer Times Calculator
Python port of PrayTime.js by Hamid Zarrabi-Zadeh
Original: https://praytimes.org
License: MIT
"""

import math
from datetime import timezone, timedelta
from typing import Union


class PrayTime:
    # Calculation methods
    METHODS = {
        'MWL':     {'name': 'Muslim World League',             'params': {'fajr': 18, 'isha': 17}},
        'ISNA':    {'name': 'Islamic Society of North America','params': {'fajr': 15, 'isha': 15}},
        'Egypt':   {'name': 'Egyptian General Authority',      'params': {'fajr': 19.5, 'isha': 17.5}},
        'Makkah':  {'name': 'Umm Al-Qura, Makkah',            'params': {'fajr': 18.5, 'isha': '90 min'}},
        'Karachi': {'name': 'University of Islamic Sciences',  'params': {'fajr': 18, 'isha': 18}},
        'Tehran':  {'name': 'Institute of Geophysics, Tehran', 'params': {'fajr': 17.7, 'isha': 14, 'maghrib': 4.5, 'midnight': 'Jafari'}},
        'Jafari':  {'name': 'Shia Ithna-Ashari (Jafari)',      'params': {'fajr': 16, 'isha': 14, 'maghrib': 4, 'midnight': 'Jafari'}},
    }

    # Default parameters
    DEFAULT_PARAMS = {
        'imsak':    '10 min',
        'fajr':     15,
        'sunrise':  0,
        'dhuhr':    0,
        'asr':      'Standard',   # 'Standard' (Shafii) or 'Hanafi'
        'sunset':   0,
        'maghrib':  '0 min',
        'isha':     15,
        'midnight': 'Standard',   # 'Standard' or 'Jafari'
    }

    TIME_NAMES = ['imsak', 'fajr', 'sunrise', 'dhuhr', 'asr', 'sunset', 'maghrib', 'isha', 'midnight']

    def __init__(self, method: str = 'MWL'):
        self.setting = dict(self.DEFAULT_PARAMS)
        self.offset = {t: 0 for t in self.TIME_NAMES}
        self.lat = 0
        self.lng = 0
        self.elv = 0
        self.tz = 0
        self.jDate = 0

        self.set_method(method)

    # ─── Public API ──────────────────────────────────────────────────────────

    def set_method(self, method: str):
        """Set calculation method by name (e.g. 'ISNA', 'MWL', 'Egypt', ...)."""
        if method in self.METHODS:
            self.adjust(self.METHODS[method]['params'])

    def adjust(self, params: dict):
        """Override individual calculation parameters."""
        self.setting.update(params)

    def tune(self, offsets: dict):
        """Add minute offsets to computed times."""
        self.offset.update(offsets)

    def getTimes(self,
                  date: Union[datetime, tuple, list],
                  coords: Union[tuple, list],
                  timezone: float = 0,
                  dst: float = 0,
                  format: str = '24h') -> dict:
        """
        Calculate prayer times for a given date and location.

        Args:
            date:     datetime object, or (year, month, day) tuple/list
            coords:   (latitude, longitude) or (latitude, longitude, elevation)
            timezone: UTC offset in hours
            dst:      Daylight saving time offset in hours (0 or 1)
            format:   Time format: '24h', '12h', '12hNS', 'Float'

        Returns:
            dict with keys: imsak, fajr, sunrise, dhuhr, asr, sunset,
                            maghrib, isha, midnight
        """
        if isinstance(date, datetime.date):
            y, m, d = date.year, date.month, date.day
        else:
            y, m, d = int(date[0]), int(date[1]), int(date[2])

        self.lat = float(coords[0])
        self.lng = float(coords[1])
        self.elv = float(coords[2]) if len(coords) > 2 else 0
        self.tz  = float(timezone) + float(dst)
        self.jDate = self._julian(y, m, d) - self.lng / (15 * 24)

        return self._compute_times(format)

    # ─── Time Formatting ─────────────────────────────────────────────────────

    def get_formatted_time(self, time: float, format: str, suffixes: list = None) -> str:
        """Convert a decimal hour value to a formatted time string."""
        if math.isnan(time):
            return '-----'
        if format == 'Float':
            return str(time)

        suffixes = suffixes or ['AM', 'PM']
        time = self._fixhour(time + 0.5 / 60)  # round to nearest minute
        hours = math.floor(time)
        minutes = math.floor((time - hours) * 60)

        suffix = suffixes[0] if hours < 12 else suffixes[1]
        hour = hours if format == '24h' else ((hours - 1) % 12 + 1)
        return f"{hour:02d}:{minutes:02d}{' ' + suffix if format != '24h' else ''}"

    # ─── Julian Date ─────────────────────────────────────────────────────────

    def _julian(self, year: int, month: int, day: int) -> float:
        if month <= 2:
            year -= 1
            month += 12
        A = math.floor(year / 100)
        B = 2 - A + math.floor(A / 4)
        return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + B - 1524.5

    # ─── Calculation Helpers ──────────────────────────────────────────────────

    def _compute_times(self, format: str) -> dict:
        times = {
            'imsak':   5,
            'fajr':    5,
            'sunrise': 6,
            'dhuhr':   12,
            'asr':     13,
            'sunset':  18,
            'maghrib': 18,
            'isha':    18,
            'midnight': 0,
        }
        # Iterate to improve accuracy
        for _ in range(1):
            times = self._compute_prayer_times(times)
        times = self._adjust_times(times)
        times = self._tune_times(times)
        return self._modify_formats(times, format)

    def _compute_prayer_times(self, times: dict) -> dict:
        t = self._day_portion(times)
        params = self.setting

        imsak   = self._sun_angle_time(self._eval(params['imsak']),   t['imsak'],   'ccw')
        fajr    = self._sun_angle_time(self._eval(params['fajr']),    t['fajr'],    'ccw')
        sunrise = self._sun_angle_time(self._rise_set_angle(self.elv), t['sunrise'], 'ccw')
        dhuhr   = self._mid_day(t['dhuhr'])
        asr     = self._asr_time(self._asr_factor(params['asr']),     t['asr'])
        sunset  = self._sun_angle_time(self._rise_set_angle(self.elv), t['sunset'])
        maghrib = self._sun_angle_time(self._eval(params['maghrib']), t['maghrib'])
        isha    = self._sun_angle_time(self._eval(params['isha']),    t['isha'])

        return {
            'imsak': imsak, 'fajr': fajr, 'sunrise': sunrise, 'dhuhr': dhuhr,
            'asr': asr, 'sunset': sunset, 'maghrib': maghrib, 'isha': isha,
            'midnight': 0,
        }

    def _adjust_times(self, times: dict) -> dict:
        params = self.setting
        tz = self.tz

        for t in times:
            times[t] += tz - self.lng / 15

        if self._is_min(params['imsak']):
            times['imsak'] = times['fajr'] - self._eval(params['imsak']) / 60
        if self._is_min(params['maghrib']):
            times['maghrib'] = times['sunset'] + self._eval(params['maghrib']) / 60
        if self._is_min(params['isha']):
            times['isha'] = times['maghrib'] + self._eval(params['isha']) / 60

        times['dhuhr'] += self._eval(params['dhuhr']) / 60

        if params['midnight'] == 'Jafari':
            times['midnight'] = times['sunset'] + self._time_diff(times['sunset'], times['fajr']) / 2
        else:
            times['midnight'] = times['sunset'] + self._time_diff(times['sunset'], times['sunrise']) / 2

        return times

    def _tune_times(self, times: dict) -> dict:
        for t in times:
            times[t] += self.offset.get(t, 0) / 60
        return times

    def _modify_formats(self, times: dict, format: str) -> dict:
        return {t: self.get_formatted_time(times[t], format) for t in times}

    # ─── Sun Calculations ─────────────────────────────────────────────────────

    def _sun_position(self, jd: float) -> dict:
        D = jd - 2451545.0
        g = self._fixangle(357.529 + 0.98560028 * D)
        q = self._fixangle(280.459 + 0.98564736 * D)
        L = self._fixangle(q + 1.9150 * self._dsin(g) + 0.0200 * self._dsin(2 * g))
        e = 23.439 - 0.00000036 * D
        RA = self._darctan2(self._dcos(e) * self._dsin(L), self._dcos(L)) / 15
        RA = self._fixhour(RA)
        D2 = self._darcsin(self._dsin(e) * self._dsin(L))
        Eq = q / 15 - RA
        return {'declination': D2, 'equation': Eq}

    def _equation_of_time(self, jd: float) -> float:
        return self._sun_position(jd)['equation']

    def _sun_declination(self, jd: float) -> float:
        return self._sun_position(jd)['declination']

    def _compute_mid_day(self, t: float) -> float:
        eqt = self._equation_of_time(self.jDate + t)
        return self._fixhour(12 - eqt)

    def _sun_angle_time(self, angle: float, t: float, direction: str = 'cw') -> float:
        decl = self._sun_declination(self.jDate + t)
        noon = self._compute_mid_day(t)
        try:
            cos_val = (-self._dsin(angle) - self._dsin(decl) * self._dsin(self.lat)) / \
                      (self._dcos(decl) * self._dcos(self.lat))
            if abs(cos_val) > 1:
                return float('nan')
            t2 = self._darccos(cos_val) / 15
        except (ZeroDivisionError, ValueError):
            return float('nan')

        return noon + (-t2 if direction == 'ccw' else t2)

    def _asr_time(self, factor: float, t: float) -> float:
        decl = self._sun_declination(self.jDate + t)
        angle = -self._darctan(1 / (factor + self._dtan(abs(self.lat - decl))))
        return self._sun_angle_time(angle, t)

    def _mid_day(self, t: float) -> float:
        return self._compute_mid_day(t)

    def _rise_set_angle(self, elevation: float = 0) -> float:
        angle = 0.0347 * math.sqrt(elevation) if elevation else 0
        return 0.833 + angle

    def _asr_factor(self, asr_param) -> float:
        factors = {'Standard': 1, 'Hanafi': 2}
        if asr_param in factors:
            return factors[asr_param]
        return self._eval(asr_param)

    def _day_portion(self, times: dict) -> dict:
        return {t: times[t] / 24 for t in times}

    # ─── Trigonometric helpers ────────────────────────────────────────────────

    def _dsin(self, d): return math.sin(math.radians(d))
    def _dcos(self, d): return math.cos(math.radians(d))
    def _dtan(self, d): return math.tan(math.radians(d))
    def _darcsin(self, x): return math.degrees(math.asin(x))
    def _darccos(self, x): return math.degrees(math.acos(x))
    def _darctan(self, x): return math.degrees(math.atan(x))
    def _darctan2(self, y, x): return math.degrees(math.atan2(y, x))
    def _darccot(self, x): return math.degrees(math.atan(1 / x))

    def _fixangle(self, a): return self._fix(a, 360)
    def _fixhour(self, a):  return self._fix(a, 24)
    def _fix(self, a, b):
        a = a - b * math.floor(a / b)
        return a + b if a < 0 else a

    # ─── Misc helpers ────────────────────────────────────────────────────────

    def _time_diff(self, time1: float, time2: float) -> float:
        return self._fixhour(time2 - time1)

    def _eval(self, val) -> float:
        """Parse a setting value — either a number or a '10 min' string."""
        if isinstance(val, (int, float)):
            return float(val)
        # e.g. '90 min' → 90
        parts = str(val).split()
        return float(parts[0])

    def _is_min(self, val) -> bool:
        """Return True if the value is a '... min' string."""
        return isinstance(val, str) and 'min' in val


# ─── Demo ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    pt = PrayTime('ISNA')

    # Location: New York City
    date     = datetime.now()
    coords   = (40.7128, -74.0060)   # lat, lng
    timezone = -5                     # EST

    times = pt.get_times(date, coords, timezone)

    print(f"Prayer times for {date.strftime('%Y-%m-%d')} — New York City")
    print("-" * 35)
    for name, t in times.items():
        print(f"  {name.capitalize():10s}: {t}")

prayTimes = PrayTime(method="Tehran")


def get_owghat(d: date, timezone_name: str = 'CET', location_latlonelev = (52.2689, 10.5268, 75.0/1000)):
    time_zone = zoneinfo.ZoneInfo(timezone_name)
    dst_date = datetime.datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=time_zone)
    # dst = 1 if dst_date.dst().seconds > 0 else 0
    dst = time_zone.utcoffset(dst_date).seconds/3600
    # print(f'dst={dst}', file=sys.stderr)
    times = prayTimes.getTimes(d, location_latlonelev, dst, format = '24h')
    # print(f'times={times} dst={dst_date.dst()}', file=sys.stderr)
    times = prayTimes.getTimes(d, location_latlonelev, dst, format = 'Float')
    times = {o:float(v) for o, v in times.items()}
    return times

def get_video_duration(fn):
    info = ffmpeg.probe(fn)
    # print(f'd: {info["format"]["duration"]}', file=sys.stderr)
    return float(info['format']['duration'])

# def f_to_hms(x):
#     return str(datetime.timedelta(seconds=x))[:-3]

def f_to_hms(x):
    h = int(x // 3600)
    m = int((x % 3600) // 60)
    s = x % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

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
            raise RuntimeError(f"File '{rl}' with none of the extensions exists.")
        r.append(rl)
    print(f"File names: {r}", file=sys.stderr)
    return r

def gen(azan_times, program, timer_file, replacements, args):
    print(f"gen {program} timer_file:{timer_file}", file=sys.stderr)
    timer_file = apply_replacements([timer_file], replacements)[0]
    timer_duration = get_video_duration(timer_file)
    # r = [(start, end, duration, file)]
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
        # start -= args.debug_time_diff * 60
        # print('gen', azan_times[name] - pre_durations.sum(), start, args.debug_time_diff)
    
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

    for o, i, d, f in r:
        print(f"r: [{f_to_hms(o)}-{f_to_hms(i)}] {f}", file=sys.stderr)

    diff = -args.debug_time_diff * 60
    rp = []
    if diff > 0:
        rp.append((24*3600 - diff, 24*3600, timer_duration, timer_file))
    s = 0
    for o, i, d, f in r:
        if s <= -diff:
            if s + i - o > -diff:
                print(f"D {f_to_hms(o)}-{f_to_hms(i)} -> {o + (-diff - s)}={f_to_hms(o + (-diff - s))}={f_to_hms(-diff - s)}+o={-diff - s}+o", file=sys.stderr)
                rp.append((o + (-diff - s), i, d, f))
        else:
            # if f == timer_file:
            #     st = o - diff
            #     en = i - diff
            #     while st >= 24*3600:
            #         st -= 24*3600
            #         en -= 24*3600
            #     if en < 24*3600:
            #         rp.append((st, en, d, f))
            #     else:
            #         rp.append((st, 24*3600, d, f))
            #         rp.append((0, en - 24*3600, d, f))
            # else:
                rp.append((o, i, d, f))
        s += i - o
    if diff < 0:
        rp.append((rp[-1][1], rp[-1][1]-diff, timer_duration, timer_file))

    for o, i, d, f in rp:
        print(f"rp: [{f_to_hms(o)}-{f_to_hms(i)}] {f}", file=sys.stderr)

    r = rp

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
    parser.add_argument('--source', default='aviny:izhamburg', help='A colon separated list of sources to be included in calculation. Items are "prayertimes", "aviny", "izhamburg".')
    parser.add_argument('--times', help='Calculated times are saving into this file.')
    parser.add_argument('--out', default='-', help='File for saving the program to. "-" for standard output.')
    parser.add_argument('--replacements', help='replacement file')
    parser.add_argument('--debug-time-diff', type=int, default=0, help='This will be added to the actual time (minutes)')
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
        print('PrayerTimes', azan_prayertimes, {o:f_to_hms(t*3600) for o, t in owghat.items()}, file=sys.stderr)

        url = f'https://prayer.aviny.com/api/prayertimes/{args.city_aviny}'
        r = requests.get(url).json()
        # print('r', r)
        replacements['{HIJRI_DAY}'] = r['TodayQamari'].split('/')[2]
        replacements['{HIJRI_MONTH}'] = r['TodayQamari'].split('/')[1]
        replacements['{HIJRI_YEAR}'] = r['TodayQamari'].split('/')[0]

        azan_r = {'imsak': r['Imsaak'], 'fajr': r['Imsaak'], 'sunrise': r['Sunrise'], 
                'dhuhr': r['Noon'], 'asr': r['Noon'], 'sunset': r['Sunset'], 
                'maghrib': r['Maghreb'], 'isha': r['Maghreb'], 'midnight': r['Midnight']}
        # print(azan_r, file=sys.stderr)
        # print({o:[int(i) for i in t.split(':')] for o, t in azan_r.items()}, file=sys.stderr)
        azan_aviny = {o:(t[0]*3600+t[1]*60+t[2]) for o, t in {o:[int(i) for i in t.split(':')] for o, t in azan_r.items()}.items()}
        print('Aviny', azan_aviny, azan_r, file=sys.stderr)

        date_yb = datetime.date(date.year, 1, 1)
        url = f'https://syber.ir/api/oghat/oneday/{location.latitude}/{location.longitude}/{(date - date_yb).days}/{date.year}/0/'
        r = requests.get(url).json()
        azan_r = {'imsak': r['imsakString'], 'fajr': r['modifiedFajrString'], 'sunrise': r['riseString'], 
                'dhuhr': r['noonString'], 'asr': r['asrString'], 'sunset': r['setString'], 
                'maghrib': r['maghribString'], 'isha': r['modifiedIshaString'], 'midnight': r['midnightString']}
        azan_izhamburg = {o:(t[0]*3600+t[1]*60+0) for o, t in {o:[int(i) for i in t.replace(' ', '').split(':')] for o, t in azan_r.items()}.items()}
        print(f'izhamburg {azan_izhamburg} {azan_r}', file=sys.stderr)

        azan_function = {'imsak': min, 'fajr': max, 'sunrise': min, 
                'dhuhr': max, 'asr': max, 'sunset': min, 
                'maghrib': max, 'isha': max, 'midnight': min}
        
        azan_with_source = {'prayertimes' : azan_prayertimes, 'aviny': azan_aviny, 'izhamburg' : azan_izhamburg}

        azan = {o:azan_function[o](*[azan_with_source[src][o] for src in args.source.split(':')]) for o in list(azan_prayertimes.keys())}
        
    if args.times:
        with open(args.times, 'w') as f:
            print(json.dumps(azan), file=f)

    print('azan {} {}'.format(azan, {o:f_to_hms(v) for o, v in azan.items()}), file=sys.stderr)

    program = gen(azan, conf['program'], conf['timer'], replacements, args)
    j = gen_text(args.city + " Azan", args.date, program)

    with open(args.out, 'w') if args.out != '-' else sys.stdout as f:
        print(j, file = f)

if __name__ == "__main__":
    main(sys.argv[1:])


    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program.json --azan fajr:06:50:00,dhuhr:12:00:00,maghrib:20:00:00 > playlist4.json
    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program.json > playlist4.json
    # ffplayout -p playlist4.json -o stream --log ffplayout.log -c ffplayout.yml
    # python gen-playlist.py --date $(date +"%Y-%m-%d") --conf network-program-hard.json > playlist4.json