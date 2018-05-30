# -*- coding: utf-8 -*-
"""
Block                                   Range       Comment
CJK Unified Ideographs                  4E00-9FFF   Common
CJK Unified Ideographs Extension A      3400-4DBF   Rare
CJK Unified Ideographs Extension B      20000-2A6DF Rare, historic
CJK Unified Ideographs Extension C      2A700–2B73F Rare, historic
CJK Unified Ideographs Extension D      2B740–2B81F Uncommon, some in current use
CJK Unified Ideographs Extension E      2B820–2CEAF Rare, historic
CJK Compatibility Ideographs            F900-FAFF   Duplicates, unifiable variants, corporate characters
CJK Compatibility Ideographs Supplement 2F800-2FA1F Unifiable variants
"""
from aqt.utils import showInfo

import logging
from . import jieba
#jieba.dt.tmp_dir = None
#jieba.dt.cache_file = None
jieba.setLogLevel(logging.CRITICAL)

def is_hanzi(char):
    ord('\u4E00')
    ranges = [('\u4E00', '\u9FFF'),
              ('\u3400', '\u4DBF'),
              #('\u20000', '\u2A6DF'),
              #('\u2A700', '\u2B73F'),
              #('\u2B740', '\u2B81F'),
              #('\u2B820', '\u2CEAF'),
              #('\u2F800', '\u2FA1F'),
              ('\uF900', '\uFAFF')]
    for start, end in ranges:
        try:
            if ord(char) >= ord(start) and ord(char) <= ord(end):
                return True
        except:
            showInfo('%s %s %s' % (len(char), len(start), len(end)))
            raise
    return False


def filter_text_hanzi(text):
    return ''.join(char for char in text if is_hanzi(char))


def has_hanzi(text):
    for c in text:
        if is_hanzi(c):
            return True
    return False

def split_hanzi(text):
    return [w for w in jieba.cut(text, cut_all=True) if has_hanzi(w)]
