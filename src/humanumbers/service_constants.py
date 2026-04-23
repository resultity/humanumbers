from __future__ import annotations

import re


TOKEN_RE = re.compile(r"%|[0-9]+(?:[.,][0-9]+)?|[^\W\d_]+")
NUMBER_RE = re.compile(r"[-+]?[0-9]+(?:[.,][0-9]+)?")
SUPPORTED_LANGUAGES = ("ru", "en", "es", "fr", "pt", "zh", "ar", "hi", "bn", "ur")
SCRIPT_HINTS = {
    "ru": re.compile(r"[А-Яа-яЁё]"),
    "zh": re.compile(r"[\u4e00-\u9fff]"),
    "ar": re.compile(r"[\u0600-\u06ff]"),
    "ur": re.compile(r"[\u0600-\u06ff]"),
    "hi": re.compile(r"[\u0900-\u097f]"),
    "bn": re.compile(r"[\u0980-\u09ff]"),
}
INTERNAL_TO_API_STYLE = {
    "neutral": "official",
    "official": "official",
    "colloquial": "colloquial",
    "oldschool": "oldschool",
    "rough": "rough",
    "profane": "profane",
}
API_TO_INTERNAL_STYLE = {
    "official": "official",
    "colloquial": "colloquial",
    "oldschool": "oldschool",
    "rough": "rough",
    "profane": "profane",
    "neutral": "neutral",
}
SMALL_NUMBER_WORDS = {
    "en": {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty"},
    "ru": {5: "пять", 6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять", 11: "одиннадцать", 12: "двенадцать", 13: "тринадцать", 14: "четырнадцать", 15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать", 19: "девятнадцать", 20: "двадцать"},
}
BOUND_NUMBER_WORDS = {
    "en": SMALL_NUMBER_WORDS["en"],
    "ru": {5: "пяти", 6: "шести", 7: "семи", 8: "восьми", 9: "девяти", 10: "десяти", 11: "одиннадцати", 12: "двенадцати", 13: "тринадцати", 14: "четырнадцати", 15: "пятнадцати", 16: "шестнадцати", 17: "семнадцати", 18: "восемнадцати", 19: "девятнадцати", 20: "двадцати"},
}
BENCHMARK_NUMBER_WORDS = {
    "en": {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"},
    "ru": {1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять", 6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять", 11: "одиннадцать", 12: "двенадцать"},
    "es": {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce"},
    "fr": {1: "un", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 7: "sept", 8: "huit", 9: "neuf", 10: "dix", 11: "onze", 12: "douze"},
    "pt": {1: "um", 2: "dois", 3: "tres", 4: "quatro", 5: "cinco", 6: "seis", 7: "sete", 8: "oito", 9: "nove", 10: "dez", 11: "onze", 12: "doze"},
    "zh": {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"},
    "ar": {1: "واحد", 2: "اثنان", 3: "ثلاث", 4: "أربع", 5: "خمس", 6: "ست", 7: "سبع", 8: "ثمان", 9: "تسع", 10: "عشر", 11: "إحدى عشرة", 12: "اثنتا عشرة"},
    "hi": {1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पांच", 6: "छह", 7: "सात", 8: "आठ", 9: "नौ", 10: "दस", 11: "ग्यारह", 12: "बारह"},
    "bn": {1: "এক", 2: "দুই", 3: "তিন", 4: "চার", 5: "পাঁচ", 6: "ছয়", 7: "সাত", 8: "আট", 9: "নয়", 10: "দশ", 11: "এগারো", 12: "বারো"},
    "ur": {1: "ایک", 2: "دو", 3: "تین", 4: "چار", 5: "پانچ", 6: "چھ", 7: "سات", 8: "آٹھ", 9: "نو", 10: "دس", 11: "گیارہ", 12: "بارہ"},
}
BENCHMARK_SCALE_BANDS = [
    {"min": 0.0, "max": 0.001, "roughness": "rough", "score": 0.97},
    {"min": 0.001, "max": 0.003, "roughness": "rough", "score": 0.95},
    {"min": 0.003, "max": 0.01, "roughness": "rough", "score": 0.94},
    {"min": 0.01, "max": 0.03, "roughness": "rough", "score": 0.93},
    {"min": 0.03, "max": 0.08, "roughness": "rough", "score": 0.92},
    {"min": 0.08, "max": 0.15, "roughness": "rough", "score": 0.9},
    {"min": 0.15, "max": 0.3, "roughness": "rough", "score": 0.88},
    {"min": 0.3, "max": 0.5, "roughness": "rough", "score": 0.86},
    {"min": 0.5, "max": 0.75, "roughness": "rough", "score": 0.85},
    {"min": 0.75, "max": 0.95, "roughness": "normal", "score": 0.9},
    {"min": 0.95, "max": 1.05, "roughness": "normal", "score": 0.98},
    {"min": 1.05, "max": 1.25, "roughness": "normal", "score": 0.9},
    {"min": 1.25, "max": 1.6, "roughness": "rough", "score": 0.88},
    {"min": 1.6, "max": 2.5, "roughness": "rough", "score": 0.89},
    {"min": 2.5, "max": 4.0, "roughness": "rough", "score": 0.91},
    {"min": 4.0, "max": 7.0, "roughness": "rough", "score": 0.92},
    {"min": 7.0, "max": 12.0, "roughness": "rough", "score": 0.93},
    {"min": 12.0, "max": 25.0, "roughness": "rough", "score": 0.94},
    {"min": 25.0, "max": 60.0, "roughness": "rough", "score": 0.95},
    {"min": 60.0, "max": 150.0, "roughness": "rough", "score": 0.96},
    {"min": 150.0, "max": float("inf"), "roughness": "rough", "score": 0.97},
]
