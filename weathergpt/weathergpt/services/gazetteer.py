"""
Place detection inside free text (news headlines).

A headline like "Flash floods hit Itanagar, Arunachal Pradesh" names a place in
prose. This finds it and returns coordinates so the alert can be pinned.

States/UT/country centroids are static geography, so a lookup table is the
right tool here (unlike weather or news, which are always fetched live).
Cities give a precise-ish pin; a state-only mention pins the state's centre and
is flagged precise=False so the UI can say "approximate location".
"""
from __future__ import annotations

import re
from typing import Optional

# name, aliases, lat, lon
STATES = [
    ("Andhra Pradesh", ["andhra pradesh", "andhra"], 15.9, 79.7),
    ("Arunachal Pradesh", ["arunachal pradesh", "arunachal"], 28.2, 94.7),
    ("Assam", ["assam"], 26.2, 92.9),
    ("Bihar", ["bihar"], 25.6, 85.1),
    ("Chhattisgarh", ["chhattisgarh"], 21.3, 81.9),
    ("Goa", ["goa"], 15.3, 74.1),
    ("Gujarat", ["gujarat"], 22.3, 71.2),
    ("Haryana", ["haryana"], 29.1, 76.1),
    ("Himachal Pradesh", ["himachal pradesh", "himachal"], 31.9, 77.2),
    ("Jharkhand", ["jharkhand"], 23.6, 85.3),
    ("Karnataka", ["karnataka"], 15.3, 75.7),
    ("Kerala", ["kerala"], 10.5, 76.3),
    ("Madhya Pradesh", ["madhya pradesh"], 23.5, 78.7),
    ("Maharashtra", ["maharashtra"], 19.7, 75.7),
    ("Manipur", ["manipur"], 24.7, 93.9),
    ("Meghalaya", ["meghalaya"], 25.5, 91.4),
    ("Mizoram", ["mizoram"], 23.2, 92.9),
    ("Nagaland", ["nagaland"], 26.2, 94.6),
    ("Odisha", ["odisha", "orissa"], 20.5, 84.4),
    ("Punjab", ["punjab"], 31.1, 75.3),
    ("Rajasthan", ["rajasthan"], 27.0, 74.2),
    ("Sikkim", ["sikkim"], 27.5, 88.5),
    ("Tamil Nadu", ["tamil nadu"], 11.1, 78.7),
    ("Telangana", ["telangana"], 18.1, 79.0),
    ("Tripura", ["tripura"], 23.9, 91.9),
    ("Uttar Pradesh", ["uttar pradesh"], 26.8, 80.9),
    ("Uttarakhand", ["uttarakhand"], 30.1, 79.0),
    ("West Bengal", ["west bengal"], 22.9, 87.9),
    ("Delhi", ["delhi", "new delhi"], 28.61, 77.21),
    ("Jammu and Kashmir", ["jammu and kashmir", "jammu & kashmir", "j&k", "kashmir"], 33.7, 76.0),
    ("Ladakh", ["ladakh", "leh"], 34.2, 77.6),
    ("Puducherry", ["puducherry", "pondicherry"], 11.9, 79.8),
    ("Andaman and Nicobar", ["andaman", "nicobar"], 11.7, 92.7),
    ("Chandigarh", ["chandigarh"], 30.73, 76.78),
    ("Lakshadweep", ["lakshadweep"], 10.6, 72.6),
]

COUNTRIES = [
    ("Nepal", ["nepal"], 28.4, 84.1),
    ("Bangladesh", ["bangladesh"], 23.7, 90.4),
    ("Sri Lanka", ["sri lanka"], 7.9, 80.8),
    ("Bhutan", ["bhutan"], 27.5, 90.4),
    ("Myanmar", ["myanmar"], 21.9, 95.9),
    ("Pakistan", ["pakistan"], 30.4, 69.3),
]

SEAS = [
    ("Bay of Bengal", ["bay of bengal"], 15.0, 88.0),
    ("Arabian Sea", ["arabian sea"], 15.0, 65.0),
]

# city, aliases, state/group, lat, lon
CITIES = [
    ("Mumbai", ["mumbai", "bombay"], "Maharashtra", 19.08, 72.88),
    ("Pune", ["pune"], "Maharashtra", 18.52, 73.86),
    ("Nagpur", ["nagpur"], "Maharashtra", 21.15, 79.09),
    ("Chennai", ["chennai"], "Tamil Nadu", 13.08, 80.27),
    ("Kolkata", ["kolkata"], "West Bengal", 22.57, 88.36),
    ("Darjeeling", ["darjeeling"], "West Bengal", 27.04, 88.26),
    ("Bengaluru", ["bengaluru", "bangalore"], "Karnataka", 12.97, 77.59),
    ("Hyderabad", ["hyderabad"], "Telangana", 17.39, 78.49),
    ("Ahmedabad", ["ahmedabad"], "Gujarat", 23.02, 72.57),
    ("Surat", ["surat"], "Gujarat", 21.17, 72.83),
    ("Vadodara", ["vadodara"], "Gujarat", 22.31, 73.18),
    ("Guwahati", ["guwahati"], "Assam", 26.14, 91.74),
    ("Dibrugarh", ["dibrugarh"], "Assam", 27.47, 94.91),
    ("Itanagar", ["itanagar"], "Arunachal Pradesh", 27.08, 93.61),
    ("Shimla", ["shimla"], "Himachal Pradesh", 31.10, 77.17),
    ("Kullu", ["kullu"], "Himachal Pradesh", 31.96, 77.11),
    ("Manali", ["manali"], "Himachal Pradesh", 32.24, 77.19),
    ("Mandi", ["mandi"], "Himachal Pradesh", 31.71, 76.93),
    ("Dehradun", ["dehradun"], "Uttarakhand", 30.32, 78.03),
    ("Kedarnath", ["kedarnath"], "Uttarakhand", 30.73, 79.07),
    ("Chamoli", ["chamoli"], "Uttarakhand", 30.40, 79.32),
    ("Srinagar", ["srinagar"], "Jammu and Kashmir", 34.08, 74.80),
    ("Patna", ["patna"], "Bihar", 25.59, 85.14),
    ("Bhubaneswar", ["bhubaneswar"], "Odisha", 20.30, 85.82),
    ("Puri", ["puri"], "Odisha", 19.81, 85.83),
    ("Visakhapatnam", ["visakhapatnam", "vizag"], "Andhra Pradesh", 17.69, 83.22),
    ("Kochi", ["kochi", "cochin"], "Kerala", 9.93, 76.27),
    ("Wayanad", ["wayanad"], "Kerala", 11.69, 76.13),
    ("Thiruvananthapuram", ["thiruvananthapuram", "trivandrum"], "Kerala", 8.52, 76.94),
    ("Jaipur", ["jaipur"], "Rajasthan", 26.91, 75.79),
    ("Lucknow", ["lucknow"], "Uttar Pradesh", 26.85, 80.95),
    ("Varanasi", ["varanasi"], "Uttar Pradesh", 25.32, 83.01),
    ("Gangtok", ["gangtok"], "Sikkim", 27.33, 88.61),
    ("Imphal", ["imphal"], "Manipur", 24.82, 93.94),
    ("Shillong", ["shillong"], "Meghalaya", 25.58, 91.89),
    ("Agartala", ["agartala"], "Tripura", 23.83, 91.29),
    ("Aizawl", ["aizawl"], "Mizoram", 23.73, 92.72),
    ("Kohima", ["kohima"], "Nagaland", 25.67, 94.11),
    ("Raipur", ["raipur"], "Chhattisgarh", 21.25, 81.63),
    ("Ranchi", ["ranchi"], "Jharkhand", 23.34, 85.31),
    ("Kathmandu", ["kathmandu"], "Nepal", 27.72, 85.32),
    ("Dhaka", ["dhaka"], "Bangladesh", 23.81, 90.41),
]

# (priority, compiled regex, record). Lower priority wins: city < state < country < sea.
_INDEX: list = []


def _pat(alias: str):
    return re.compile(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", re.I)


for name, aliases, lat, lon in STATES:
    for a in aliases:
        _INDEX.append((1, _pat(a), {"name": name, "group": name, "lat": lat, "lon": lon, "precise": False}))
for name, aliases, lat, lon in COUNTRIES:
    for a in aliases:
        _INDEX.append((2, _pat(a), {"name": name, "group": name, "lat": lat, "lon": lon, "precise": False}))
for name, aliases, lat, lon in SEAS:
    for a in aliases:
        _INDEX.append((3, _pat(a), {"name": name, "group": name, "lat": lat, "lon": lon, "precise": False}))
for name, aliases, group, lat, lon in CITIES:
    for a in aliases:
        _INDEX.append((0, _pat(a), {"name": f"{name}, {group}", "group": group, "lat": lat, "lon": lon, "precise": True}))


def find_region(text: str) -> Optional[dict]:
    """Best place mentioned in text: city beats state beats country beats sea;
    ties go to whichever appears first."""
    if not text:
        return None
    best = None
    for prio, rx, rec in _INDEX:
        m = rx.search(text)
        if m:
            cand = (prio, m.start(), rec)
            if best is None or cand[:2] < best[:2]:
                best = cand
    return dict(best[2]) if best else None
