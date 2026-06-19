#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#Copyright (c) 2026 Szymon Wolarz
#Licensed under the MIT License. See LICENSE file in the project root for full license information.

"""
MODULE: algorithms.py
ROLE: Tool Layer
DESCRIPTION:
CORE LOGIC v6.7 (COVERAGE VALIDATION) - Script vs Transcript Alignment.
Features:
- ANALYZE (COMPARE) v5.0 implementation
- SuperNormalization (SuperCompare) for robust matching
- Numeric Greed (Handling split numbers/IPs)
- Advanced Retake Detection (Fuzzy Anchor + Lookahead with noise skip)
- PATCH v5.8: NUMERIC PROTECTION & STRICT TRACE (Smart Grouping)
- PATCH v5.9: INSERTION PRIORITY (Fixes "any settings" issue)
- PATCH v6.0: ANCHOR SECURITY & DEEP YELLOW (Fixes Blue Ocean & Missing Sync)
- PATCH v6.1: FUZZY SKIP & TAIL CHECK (Fuzzy Deletion Lookahead & Trailing Missing)
- PATCH v6.3: YELLOW MISSING REPORT (Correctly captures internal & tail missing words)
- PATCH v6.4: ANTI-FREEZE HYBRID RETURN (Fixes 'infinite loop' caused by tuple return)
- PATCH v6.5: DISTANCE PENALTY (Fixes False Long-Distance Retake bugs)
- PATCH v6.6: HEAD SYNC & PDF NORMALIZATION (Fixes script start offset and messy PDF whitespaces)
- PATCH v6.7: COVERAGE VALIDATION (Ensures found words/retakes are not marked missing)
- DEBUG MODE: RGB Pattern Injection
- Handling of Deletions and Insertions
- Document readers (PDF/DOCX)
- [NEW] GUI Helpers (Logic extracted from presentation layer)
- [NEW] HALLUCINATION SHIELD: Algorithms explicitly ignore _is_hallucination tags to preserve them.
- [STAGE 9] HALLUCINATION SANITIZER: sanitize_hallucinations() strips model repetition loops before alignment.
- [STAGE 9] RETAKE SENSITIVITY: Short-word (< 4 chars) retake anchors use lowered fuzzy threshold (0.40).
"""

import re
import difflib
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from osdoc import log_info
from zh_mapping import to_simplified

try:
    import jieba
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    from pypinyin import lazy_pinyin
    HAS_PYPINYIN = True
except ImportError:
    HAS_PYPINYIN = False



# ==========================================
# CONSTANTS & CONFIG
# ==========================================

STOP_WORDS = {"a", "an", "the", "in", "on", "at", "to", "of", "i", "you", "he", "she", "it", "we", "they", "is", "are", "and", "or"}

# Fuzzy Thresholds
THRESH_LONG = 0.65   # v7.5 Relaxed from 0.70 to reduce false positives
THRESH_MID = 0.55    # v7.5 Relaxed from 0.65
THRESH_SHORT = 0.45  # v7.5 Relaxed from 0.50

# ==========================================
# 0. HALLUCINATION SANITIZER (STAGE 9)
# ==========================================

def sanitize_hallucinations(transcript_words):
    """
    STAGE 9: Removes technical hallucination loops from raw Whisper output.
    A hallucination run is defined as: the same word repeating > 3 times
    consecutively AND each occurrence lasting < 0.2 seconds (suspiciously fast).
    Action: keep the first 2 instances, drop the rest, log a warning.
    """
    if not transcript_words:
        return transcript_words

    cleaned = []
    i = 0
    total_dropped = 0

    while i < len(transcript_words):
        w = transcript_words[i]
        raw_text = re.sub(r'[^\w]', '', w.get('text', '')).lower()

        # Count identical consecutive words
        run_count = 1
        while (i + run_count < len(transcript_words)):
            cand_text = re.sub(r'[^\w]', '', transcript_words[i + run_count].get('text', '')).lower()
            if cand_text == raw_text:
                run_count += 1
            else:
                break

        if run_count > 3:
            # Hallucination criterion: all words in the run are suspiciously short (< 0.2 s)
            all_short = all(
                (transcript_words[i + k].get('end', 0) - transcript_words[i + k].get('start', 0)) < 0.2
                for k in range(run_count)
            )
            if all_short:
                # Keep the first 2 instances, drop the rest
                cleaned.extend(transcript_words[i:i + 2])
                dropped = run_count - 2
                total_dropped += dropped
                i += run_count
                continue

        # Normal path: keep the word and advance
        cleaned.append(w)
        i += 1

    if total_dropped > 0:
        log_info(f"Sanitizer removed {total_dropped} hallucinated words.")

    return cleaned


# ==========================================
# 1. FILE HANDLING (Helpers)
# ==========================================

def read_docx_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml_content = z.read('word/document.xml')
        tree = ET.fromstring(xml_content)
        text_parts = []
        for elem in tree.iter():
            if elem.tag.endswith('}t'):
                if elem.text:
                    text_parts.append(elem.text)
        
        full_text = "\n".join(text_parts)
        # PATCH v6.6: Aggressive whitespace normalization
        # Replaces newlines, tabs, and multiple spaces with a single space.
        return re.sub(r'\s+', ' ', full_text).strip()
    except Exception as e:
        return f"[Error reading .docx] {e}"

def read_pdf_text(path):
    if not HAS_PYPDF:
        return "[Error] pypdf library missing."
    try:
        reader = pypdf.PdfReader(path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + " " # Use space instead of newline to avoid joining words
        
        # PATCH v6.6: Aggressive whitespace normalization for PDFs
        # PDFs often have weird line breaks that break tokenization.
        return re.sub(r'\s+', ' ', text).strip()
    except Exception as e:
        return f"[Error reading PDF] {e}"

# ==========================================
# 2. PREPROCESSING & TOKENIZATION v5.0
# ==========================================

def has_cjk(text):
    """Checks if text contains CJK characters (Chinese, Japanese, Korean)."""
    if not text:
        return False
    return any(
        '\u4e00' <= char <= '\u9fff' or
        '\u3400' <= char <= '\u4dbf' or
        '\uf900' <= char <= '\ufaff' or
        '\u3040' <= char <= '\u309f' or
        '\u30a0' <= char <= '\u30ff' or
        '\uac00' <= char <= '\ud7a3'
        for char in text
    )

def super_clean(text):
    """
    Funkcja pomocnicza 'SuperCompare' (część A).
    Usuwa WSZYSTKO co nie jest cyfrą, literą lub znakiem CJK/Japonia/Korea.
    """
    if not text: return ""
    cleaned = re.sub(
        r'[^a-z0-9\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]',
        '',
        text.lower()
    )
    return to_simplified(cleaned)

def tokenize_v5(text):
    """
    Tokenizacja v5.0:
    1. Lowercase.
    2. Split po białych znakach.
    3. Strip interpunkcji KOŃCZĄCEJ/ZACZYNAJĄCEJ (.,?!:;), ale ZACHOWANIE wewnętrznej (192.168.0.1, wi-fi, don't).
    """
    if not text: return []
    
    # Normalize traditional to simplified Chinese
    text = to_simplified(text)
    
    if HAS_JIEBA:
        words = jieba.cut(text)
        clean_tokens = []
        cjk_and_ascii_punct = ".,?!:;\"'()[]{}<>，。！？：；“”‘’（）【】《》、…—"
        for w in words:
            stripped = w.strip(cjk_and_ascii_punct)
            if stripped and stripped.strip():
                clean_tokens.append(stripped.lower())
        return clean_tokens
    else:
        # Fallback to character-by-character regex split
        text = re.sub(r'([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3])', r' \1 ', text)
        
        # Pre-clean excessive whitespace to be safe
        text = re.sub(r'\s+', ' ', text)
        
        raw_tokens = text.lower().split()
        clean_tokens = []
        
        # CJK and ASCII punctuation characters
        cjk_and_ascii_punct = ".,?!:;\"'()[]{}<>，。！？：；“”‘’（）【】《》、…—"
        
        for t in raw_tokens:
            # Usuń interpunkcję z krawędzi słowa
            stripped = t.strip(cjk_and_ascii_punct)
            if stripped:
                clean_tokens.append(stripped)
                
        return clean_tokens

def segment_and_merge_cjk(words_data):
    if not words_data:
        return words_data
    if not HAS_JIEBA:
        return words_data
        
    # Group consecutive active words
    groups = []
    current_group = []
    for idx, w in enumerate(words_data):
        is_sil = w.get('type') in ('silence', 'inaudible') or w.get('is_inaudible') or w.get('_is_hallucination')
        if is_sil:
            if current_group:
                groups.append(current_group)
                current_group = []
            groups.append(idx)
        else:
            current_group.append(idx)
    if current_group:
        groups.append(current_group)
        
    new_words_data = []
    for item in groups:
        if isinstance(item, int):
            new_words_data.append(words_data[item])
        else:
            # Check if this group has any CJK characters
            has_any_cjk = False
            full_text = ""
            char_to_word_idx = []
            
            for idx in item:
                w_text = words_data[idx].get('text', '')
                if has_cjk(w_text):
                    has_any_cjk = True
                for char in w_text:
                    full_text += char
                    char_to_word_idx.append(idx)
            
            if not has_any_cjk:
                # English or other non-CJK group: keep original items exactly as they are
                for idx in item:
                    new_words_data.append(words_data[idx])
                continue
                
            # CJK-active group: segment and merge using jieba
            if not full_text:
                continue
                
            simp_text = to_simplified(full_text)
            segmented_simp = list(jieba.cut(simp_text))
            
            char_ptr = 0
            for word_simp in segmented_simp:
                word_len = len(word_simp)
                if word_len == 0:
                    continue
                
                word_orig = full_text[char_ptr : char_ptr + word_len]
                word_indices = char_to_word_idx[char_ptr : char_ptr + word_len]
                char_ptr += word_len
                
                if not word_indices:
                    continue
                    
                first_w = words_data[word_indices[0]]
                last_w = words_data[word_indices[-1]]
                
                merged_word = {
                    "text": word_orig,
                    "start": first_w.get("start", 0.0),
                    "end": last_w.get("end", 0.0),
                    "type": first_w.get("type", "word"),
                    "id": first_w.get("id", 0),
                    "seg_start": first_w.get("seg_start", 0.0),
                    "seg_end": last_w.get("seg_end", 0.0),
                    "is_segment_start": first_w.get("is_segment_start", False),
                }
                for k, v in first_w.items():
                    if k not in merged_word:
                        merged_word[k] = v
                        
                new_words_data.append(merged_word)
                
    for i, w in enumerate(new_words_data):
        w['id'] = i
        
    return new_words_data


# ==========================================
# 3. FUZZY LOGIC & PHONETICS
# ==========================================

def simplified_metaphone(word):
    """Poor Man's Metaphone implementation."""
    if not word: return ""
    s = word.lower()
    s = re.sub(r'[bfpv]', '1', s)
    s = re.sub(r'[cgjkqsxz]', '2', s)
    s = re.sub(r'[dt]', '3', s)
    s = re.sub(r'l', '4', s)
    s = re.sub(r'[mn]', '5', s)
    s = re.sub(r'r', '6', s)
    if len(s) > 1:
        s = s[0] + re.sub(r'[aeiouy]', '', s[1:])
    s = re.sub(r'(.)\1+', r'\1', s)
    return s

def calculate_similarity(s1, s2):
    # FIX IN-07: quick_ratio() jest 3-5x szybsze, a wystarcza do progowania fuzzy matchingu
    return difflib.SequenceMatcher(None, s1, s2).quick_ratio()

def check_fuzzy_match(s1, s2):
    """
    Weryfikacja tekstowa na podstawie wersji 'super_clean' (wg specyfikacji v5.0).
    """
    c1 = super_clean(s1)
    c2 = super_clean(s2)
    
    if not c1 or not c2: return False
    
    if has_cjk(c1) or has_cjk(c2):
        return c1 == c2
        
    sim = calculate_similarity(c1, c2)
    length = max(len(c1), len(c2))
    min_length = min(len(c1), len(c2))
    
    # v7.5 Anti-Cascade: Prevent absurd matches like "are" vs "a"
    if length > 0 and (min_length / length) < 0.4:
        return False
    
    threshold = THRESH_LONG
    if length < 4: threshold = THRESH_SHORT
    elif length <= 7: threshold = THRESH_MID
    
    if sim >= threshold:
        return True
        
    # Fonetyka dla niepewnych
    if sim >= 0.50:
        ph1 = simplified_metaphone(c1)
        ph2 = simplified_metaphone(c2)
        if ph1 and ph2 and ph1 == ph2:
            return True
            
    return False

# ==========================================
# 4. MAIN ALGORITHM CLASS (v5.0)
# ==========================================

class AnalysisResult(list):
    """
    PATCH v6.4: Klasa hybrydowa - Lista z atrybutami.
    Zachowuje się jak lista słów (dla engine.py),
    ale przechowuje missing_indices (dla gui.py).
    Rozwiązuje problem 'zamrożenia' (crashu wątku) przez niezgodność typów.
    """
    def __init__(self, iterable=None):
        super().__init__(iterable if iterable else [])
        self.missing_indices = []


def apply_debug_rgb_pattern(words_data):
    """
    Debug Mode: Colors entire transcript in Red-Green-Blue cycle.
    Used to test timestamp alignment and timeline cut precision.
    
    Pattern:
    - RED (bad)
    - GREEN (typo)
    - BLUE (repeat)
    """
    pattern = ['bad', 'typo', 'repeat']
    cycle_idx = 0
    
    log_info("[DEBUG] Applying RGB Pattern to all words...")
    
    for w in words_data:
        # Skip functional blocks
        if w.get('type') in ['silence', 'inaudible']:
            continue
            
        # Select status based on cycle
        status = pattern[cycle_idx % 3]
        
        w['status'] = status
        w['selected'] = True
        w['manual_status'] = status # Force persistence
        w['is_auto'] = False
        
        cycle_idx += 1
        
    result = AnalysisResult(words_data)
    result.missing_indices = [] # No missing script in debug mode
    return result


class CompareEngine:
    """
    V7 Engine (Global Anchor + Gap Analysis)
    Implements a strict binary trap for 94% accuracy.
    """
    def __init__(self, script_text, words_data, algo_settings=None):
        self.script_text = script_text
        self.words_data = words_data

    def run(self):

        def clean_text(text): 
            return re.sub(r'[^\w\u4e00-\u9fff]', '', text)

        def char_match(py1, py2, c1, c2):
            if c1 == c2 and c1 != "": return 1.0
            if py1 == py2 and py1 != "": return 0.8
            if py1 and py2 and py1[0] == py2[0]: return 0.2
            return 0.0

        def global_alignment(T_pys, S_pys, T_chars, S_chars):
            M = len(T_pys)
            N = len(S_pys)
            dp = [[0.0] * (N + 1) for _ in range(M + 1)]
            ptr = [[0] * (N + 1) for _ in range(M + 1)]
            
            for i in range(1, M + 1):
                dp[i][0] = i * -0.5
                ptr[i][0] = 1
            for j in range(1, N + 1):
                dp[0][j] = j * -1.0
                ptr[0][j] = 2
                
            for i in range(1, M + 1):
                for j in range(1, N + 1):
                    score = char_match(T_pys[i-1], S_pys[j-1], T_chars[i-1], S_chars[j-1])
                    match = dp[i-1][j-1] + score
                    delete = dp[i-1][j] - 0.5
                    insert = dp[i][j-1] - 1.0
                    
                    best = max(match, delete, insert)
                    dp[i][j] = best
                    if best == match: ptr[i][j] = 0
                    elif best == delete: ptr[i][j] = 1
                    else: ptr[i][j] = 2
                    
            i, j = M, N
            alignment = []
            while i > 0 or j > 0:
                if ptr[i][j] == 0:
                    alignment.append(('match', i-1, j-1))
                    i -= 1; j -= 1
                elif ptr[i][j] == 1:
                    alignment.append(('T_gap', i-1, None))
                    i -= 1
                else:
                    alignment.append(('S_gap', None, j-1))
                    j -= 1
                    
            alignment.reverse()
            return alignment

        def local_similarity(gap_T_pys, anchor_T_pys):
            if len(gap_T_pys) == 0 or len(anchor_T_pys) == 0: return 0.0
            M = len(gap_T_pys)
            N = len(anchor_T_pys)
            dp = [[0.0] * (N + 1) for _ in range(M + 1)]
            max_score = 0
            for i in range(1, M + 1):
                for j in range(1, N + 1):
                    sc = 1.0 if gap_T_pys[i-1] == anchor_T_pys[j-1] else 0.0
                    match = dp[i-1][j-1] + sc
                    delete = dp[i-1][j] - 0.5
                    insert = dp[i][j-1] - 0.5
                    best = max(0.0, match, delete, insert)
                    dp[i][j] = best
                    if best > max_score:
                        max_score = best
            return max_score / M if M > 0 else 0.0

        S_chars = [c for c in clean_text(self.script_text)]
        S_pys = [lazy_pinyin(c)[0] if lazy_pinyin(c) else "" for c in S_chars]

        T_chars = []
        T_pys = []
        word_mapping = []
        for w_idx, w in enumerate(self.words_data):
            if w.get('type') in ['silence', 'inaudible'] or w.get('is_inaudible') or w.get('_is_hallucination'):
                w['status'] = w.get('manual_status')
                w['selected'] = bool(w.get('status'))
                w['is_auto'] = False
                continue
                
            clean = clean_text(w.get('text', ''))
            for c in clean:
                T_chars.append(c)
                T_pys.append(lazy_pinyin(c)[0] if lazy_pinyin(c) else "")
                word_mapping.append(w_idx)

        alignment = global_alignment(T_pys, S_pys, T_chars, S_chars)
        
        blocks = []
        current_type = None
        curr_T = []
        for t, i, j in alignment:
            if t != current_type:
                if current_type is not None:
                    blocks.append({'type': current_type, 'T_indices': curr_T})
                current_type = t
                curr_T = []
            if i is not None:
                curr_T.append(i)
        if current_type is not None:
            blocks.append({'type': current_type, 'T_indices': curr_T})

        for w in self.words_data:
            if w.get('type') not in ['silence', 'inaudible'] and not w.get('is_inaudible') and not w.get('_is_hallucination'):
                w['status'] = 'normal'
                w['selected'] = False
                w['is_auto'] = True

        for idx, block in enumerate(blocks):
            if block['type'] == 'T_gap':
                next_match_T = []
                for next_idx in range(idx + 1, len(blocks)):
                    if blocks[next_idx]['type'] == 'match':
                        next_match_T = blocks[next_idx]['T_indices']
                        break
                
                if len(next_match_T) > 0 and len(block['T_indices']) > 0:
                    gap_pys = [T_pys[i] for i in block['T_indices']]
                    anchor_pys = [T_pys[i] for i in next_match_T][:30]
                    similarity = local_similarity(gap_pys, anchor_pys)
                    status = 'repeat' if similarity > 0.5 else 'bad'
                else:
                    status = 'bad'
                    
                for t_idx in block['T_indices']:
                    w_idx = word_mapping[t_idx]
                    self.words_data[w_idx]['status'] = status
                    self.words_data[w_idx]['selected'] = True
                    self.words_data[w_idx]['is_auto'] = True


def compare_script_to_transcript(script_text, words_data, algo_settings=None):
    """
    Wrapper dla silnika v7.0 DP.
    Includes Debug Interceptor for "$ R G B" code.
    STAGE 9: Applies sanitize_hallucinations() before alignment to strip model loops.
    """
    
    # --- DEBUG INTERCEPTOR ---
    clean_code = script_text.strip().replace(" ", "").upper()
    if clean_code == "$RGB":
        return apply_debug_rgb_pattern(words_data)
    # -------------------------

    # STAGE 9: Strip hallucination loops from raw transcript before analysis
    words_data = sanitize_hallucinations(words_data)

    engine = CompareEngine(script_text, words_data, algo_settings=algo_settings)
    return engine.run()
    return engine.run()

def absorb_inaudible_into_repeats(words_data):
    """
    Scalanie luk 'inaudible' pomiędzy blokami 'repeat'.
    """
    n = len(words_data)
    if n < 3: return words_data
    
    target_status = 'repeat'
    
    # Helpers
    def get_prev_effective_index(start_i):
        idx = start_i - 1
        while idx >= 0:
            if words_data[idx].get('type') != 'silence': return idx
            idx -= 1
        return -1

    def get_next_effective_index(start_i):
        idx = start_i
        while idx < n:
            if words_data[idx].get('type') != 'silence': return idx
            idx += 1
        return -1

    i = 0
    while i < n:
        if words_data[i].get('type') == 'silence':
            i += 1
            continue

        if words_data[i].get('is_inaudible'):
            start_idx = i
            curr = i
            while curr < n:
                w = words_data[curr]
                if w.get('is_inaudible') or w.get('type') == 'silence': curr += 1
                else: break
            
            end_idx = curr
            left_idx = get_prev_effective_index(start_idx)
            prev_ok = (left_idx >= 0 and words_data[left_idx].get('status') == target_status)
            effective_right = get_next_effective_index(end_idx) if end_idx < n else -1
            next_ok = (effective_right != -1 and words_data[effective_right].get('status') == target_status)
            
            if prev_ok and next_ok:
                for k in range(start_idx, end_idx):
                    if words_data[k].get('is_inaudible'):
                        words_data[k]['status'] = 'repeat'
                        words_data[k]['selected'] = False
            i = end_idx
        else:
            i += 1
    return words_data

def analyze_repeats(words_data, show_inaudible=True, algo_settings=None):
    """Legacy Standalone Analyzer (Without Script)."""
    if algo_settings is None:
        algo_settings = {}
    # 1. Smart Reset - Wipeout omijający halucynacje, inaudible i ręczne poprawki
    for w in words_data:
        if w.get('_is_hallucination') or w.get('type') in ['silence', 'inaudible'] or w.get('is_inaudible'):
            continue
            
        # Wyczyść tylko to co jest przypisane jako repeat (żeby nie psuć np. bad z engine)
        if w.get('status') == 'repeat':
            w['status'] = w.get('manual_status') # Przywracamy warstwę bazową
            w['selected'] = (w['status'] in ['bad', 'inaudible', 'typo'])
            w['is_auto'] = False

    # 2. Linear Flow
    linear_flow = []
    for idx, w in enumerate(words_data):
        if w.get('type') in ['silence', 'inaudible']: continue
        if w.get('is_inaudible'): continue
        if w.get('_is_hallucination'): continue # SKIPPING HALLUCINATIONS
        
        # Normalize to simplified
        raw_text = to_simplified(w.get('text', ''))
        txt = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3]', '', raw_text).lower()
        if not txt or txt in STOP_WORDS: continue
        
        if HAS_JIEBA:
            # Word-level CJK tokens
            linear_flow.append({'text': txt, 'real_idx': idx})
        else:
            # Fallback to character-by-character CJK segments
            if has_cjk(txt):
                for char in txt:
                    if char.strip():
                        linear_flow.append({'text': char, 'real_idx': idx})
            else:
                linear_flow.append({'text': txt, 'real_idx': idx})

    n_flow = len(linear_flow)
    marked_indices = set()
    
    # 3. N-gram
    i = 0
    LOOKAHEAD = int(algo_settings.get('algo_retake_lookahead', 30))
    MIN_LEN = 2
    
    # FIX OP-02: Mapowanie pozycji słów O(n) przed pętlą zamiast O(n²) nested loop
    word_positions = defaultdict(list)
    for idx_flow, entry in enumerate(linear_flow):
        word_positions[entry['text']].append(idx_flow)
        
    while i < n_flow:
        curr = linear_flow[i]
        limit = min(n_flow, i + LOOKAHEAD)
        best_len = 0
        best_target = -1
        
        # Szybkie wyszukiwanie tylko tych indeksów, które mają to samo słowo
        potential_targets = [idx for idx in word_positions[curr['text']] if i < idx < limit]
        
        for j in potential_targets:
            k = 1
            while (i + k < n_flow) and (j + k < n_flow):
                if linear_flow[i+k]['text'] == linear_flow[j+k]['text']: k += 1
                else: break
            
            if k >= MIN_LEN and k > best_len:
                best_len = k
                best_target = j
        
        if best_len >= MIN_LEN:
            for m in range(best_len):
                marked_indices.add(linear_flow[i+m]['real_idx'])
                marked_indices.add(linear_flow[best_target+m]['real_idx'])
        i += 1

    count = 0
    for idx in marked_indices:
        words_data[idx]['status'] = 'repeat'
        words_data[idx]['selected'] = False
        count += 1
        
    return words_data, count

# ==========================================
# 6. GUI LOGIC HELPERS (Decoupled Logic)
# ==========================================

def apply_auto_filler_logic(words_data, fillers, is_enabled):
    fillers_lower = [to_simplified(f.lower()) for f in fillers]
    for w in words_data:
        raw_text = to_simplified(w.get('text', ''))
        clean_text = raw_text.strip(".,?!:;\"'()[]{}<>，。！？：；“”‘’„”（）【】《》、…—").lower()
        if is_enabled and clean_text in fillers_lower:
            if not w.get('manual_status'): # Do not overwrite manual markings
                w['status'] = 'bad'
                w['is_auto'] = True
                w['selected'] = True
        else:
            # CLEANUP: If it was auto-marked previously, but no longer qualifies, clear it
            if w.get('is_auto'):
                w['status'] = w.get('manual_status')
                w['is_auto'] = False
                w['selected'] = bool(w['status'])
    return words_data

def propagate_status_change(words_data, target_id, new_status):
    """
    Calculates which words need status updates based on 'inaudible' grouping.
    Returns a list of tuples: (word_id, final_status).
    Also updates 'manual_status' to allow base-layer persistence.
    """
    updates = []
    
    if target_id < 0 or target_id >= len(words_data):
        return updates

    target_w = words_data[target_id]

    if target_w.get('is_inaudible'):
        # Expand selection to cover contiguous block of inaudible/silence
        start = target_id
        while start > 0:
            prev = words_data[start-1]
            if prev.get('is_inaudible') or prev.get('type') == 'silence':
                start -= 1
            else:
                break
        
        end = target_id
        while end < len(words_data)-1:
            nxt = words_data[end+1]
            if nxt.get('is_inaudible') or nxt.get('type') == 'silence':
                end += 1
            else:
                break
        
        for i in range(start, end + 1):
            w = words_data[i]
            if w.get('is_inaudible'):
                final_status = new_status
                
                # Apply in-place change. Removed the hardcoded fallback to 'inaudible'
                # to allow the eraser tool to properly clear the fragment base layer.
                w['status'] = final_status
                w['manual_status'] = final_status # Base layer
                w['is_auto'] = False # Remove auto flag
                
                w['selected'] = (final_status in ['bad', 'inaudible', 'typo', 'repeat'])
                updates.append((w['id'], final_status))
    else:
        # Standard word update
        w_obj = target_w
        
        w_obj['status'] = new_status
        w_obj['manual_status'] = new_status # Base layer
        w_obj['is_auto'] = False # Remove auto flag
        
        w_obj['selected'] = (new_status in ['bad', 'inaudible', 'typo', 'repeat'])
        updates.append((w_obj['id'], new_status))
        
    return updates

def calculate_script_missing_ranges(text_content, missing_indices):
    """
    Maps missing word indices to character ranges in the raw script text.
    Returns list of (start_index, end_index) tuples, where indices 
    are absolute character positions in the text.
    """
    if not missing_indices:
        return []

    tokens_map = []
    pattern = re.compile(r'\S+')
    matches = list(pattern.finditer(text_content))
    
    # Filter matches to build a valid token map (skipping pure punctuation if tokenizer did so)
    for m in matches:
        raw = m.group()
        # Same cleaning logic as in engine/algo to ensure index alignment
        clean = raw.strip(".,?!:;\"'()[]{}<>，。！？：；“”‘’„”（）【】《》、…—")
        if clean:
            tokens_map.append(m)

    ranges = []
    for idx in missing_indices:
        if idx < len(tokens_map):
            match = tokens_map[idx]
            ranges.append((match.start(), match.end()))
            
    return ranges


# ==========================================
# 7. SIDE-BY-SIDE SCRIPT / TRANSCRIPT VIEW
# ==========================================

def _script_lines_for_side_by_side(script_text):
    """
    Intelligently splits the script into logical sentences/rows.
    - Preserves double newlines (paragraphs).
    - Merges single newlines (hard wraps).
    - Splits paragraphs into sentences based on punctuation followed by a capital letter.
    - Ignores rows that contain no alphanumeric characters (e.g., just "..." or "-").
    """
    text = script_text.replace('\r\n', '\n')
    paragraphs = re.split(r'\n\s*\n', text)
    final_rows = []
    
    for para in paragraphs:
        # Collapse single newlines and multiple spaces within a paragraph
        para = re.sub(r'\s+', ' ', para).strip()
        if not para:
            continue
            
        # We find sentence boundaries: [.!?] (optionally followed by quotes/brackets)
        # then spaces, then an Uppercase letter or Number.
        # We insert a newline before the Uppercase letter to split it cleanly.
        # \1 captures the punctuation, \2 captures the Uppercase letter.
        para = re.sub(r'([.!?]+["\')\]]?)\s+([A-Z0-9ŚĆŻŹĄĘÓŁŃ])', r'\1\n\2', para)
        
        for sentence in para.split('\n'):
            sentence = sentence.strip()
            if not re.search(r'\w', sentence):
                continue
                
            # Sub-sentence Flow Breaker:
            # Subdivide extremely long sentences at logical pauses (,, ;, :, —, ...) 
            # while ensuring we don't over-fragment (each piece must have >= 5 words).
            chunks = re.split(r'([,;:—]+|\.{2,})\s+', sentence)
            
            sub_rows = []
            curr_str = ""
            curr_words = 0
            
            i = 0
            while i < len(chunks):
                text_part = chunks[i]
                punct_part = chunks[i+1] if i + 1 < len(chunks) else ""
                
                segment = text_part + punct_part
                seg_words = len(segment.split())
                
                if curr_words == 0:
                    curr_str = segment
                    curr_words = seg_words
                else:
                    if curr_words >= 5:
                        sub_rows.append(curr_str.strip())
                        curr_str = segment
                        curr_words = seg_words
                    else:
                        curr_str += " " + segment
                        curr_words += seg_words
                i += 2
                
            if curr_str:
                # Only merge backwards if the trailing thought is extremely short (< 3 words)
                if curr_words < 3 and len(sub_rows) > 0:
                    sub_rows[-1] += " " + curr_str.strip()
                else:
                    sub_rows.append(curr_str.strip())
                    
            for r in sub_rows:
                if re.search(r'\w', r):
                    final_rows.append(r)
                
    if not final_rows:
        return [script_text.strip()] if script_text.strip() else []
        
    return final_rows


def _tokens_from_script_lines(lines):
    tokens = []
    for row_idx, line in enumerate(lines):
        for match in re.finditer(r"\S+", line):
            raw = match.group(0)
            clean = super_clean(raw)
            if clean:
                tokens.append({"text": raw, "clean": clean, "row": row_idx})
    return tokens


def _tokens_from_words_data(words_data):
    tokens = []
    for w in words_data or []:
        if w.get("type") in ("silence", "inaudible") or w.get("is_inaudible"):
            continue
        raw_text = w.get("text", "").strip()
        raw_text = to_simplified(raw_text)
        
        clean_full = super_clean(raw_text)
        if not clean_full:
            continue
            
        if HAS_JIEBA:
            # Word-level CJK tokens using Jieba
            tokens.append({
                "text": w.get("text", "").strip(),
                "clean": clean_full,
                "status": w.get("status"),
                "word_id": w.get("id"),
                "is_segment_start": w.get("is_segment_start", False),
                "start": w.get("start", 0.0),
                "original_word": w,
            })
        else:
            # Fallback to character-by-character CJK tokens
            i_char = 0
            while i_char < len(clean_full):
                char = clean_full[i_char]
                if has_cjk(char):
                    tokens.append({
                        "text": char,
                        "clean": char,
                        "status": w.get("status"),
                        "word_id": w.get("id"),
                        "is_segment_start": w.get("is_segment_start", False),
                        "start": w.get("start", 0.0),
                        "original_word": w,
                    })
                    i_char += 1
                else:
                    start_non_cjk = i_char
                    while i_char < len(clean_full) and not has_cjk(clean_full[i_char]):
                        i_char += 1
                    non_cjk_part = clean_full[start_non_cjk:i_char]
                    if non_cjk_part:
                        tokens.append({
                            "text": non_cjk_part,
                            "clean": non_cjk_part,
                            "status": w.get("status"),
                            "word_id": w.get("id"),
                            "is_segment_start": w.get("is_segment_start", False),
                            "start": w.get("start", 0.0),
                            "original_word": w,
                        })
    return tokens


def _side_by_side_text_from_transcript_tokens(tokens):
    """
    Keeps detected retake runs visually separated. The GUI renders newline
    characters as a fresh line inside the transcript cell.
    """
    if not tokens:
        return ""

    parts = []
    prev_repeat = False
    for tok in tokens:
        is_repeat = tok.get("status") == "repeat"
        if is_repeat and parts and not prev_repeat:
            parts.append("\n")
        elif parts and parts[-1] != "\n":
            parts.append(" ")
        parts.append(tok.get("text", ""))
        prev_repeat = is_repeat
    return "".join(parts).strip()


def build_side_by_side_alignment(script_text, words_data):
    """
    Builds rows for the side-by-side compare view.
    
    Strategy: Group by SCRIPT LINES, not transcript segments.
    1. Split script into lines (user line-breaks, or sentence fallback).
    2. Use difflib to map each transcript token to its best-matching script line.
    3. Absorb repeat runs into the script line they're repeating.
    4. Unmatched transcript tokens (improv) → own row with empty script.
    5. Unmatched script lines (unspoken) → own row with empty transcript.
    """
    script_lines = _script_lines_for_side_by_side(script_text)
    trans_tokens = _tokens_from_words_data(words_data)

    if not script_lines and not trans_tokens:
        return []

    # Build flat script token list with line indices
    script_tokens = []
    for line_idx, line in enumerate(script_lines):
        line = to_simplified(line)
        if HAS_JIEBA:
            words = jieba.cut(line)
            for w in words:
                clean = super_clean(w)
                if clean:
                    script_tokens.append({"text": w, "clean": clean, "line": line_idx})
        else:
            line_seg = re.sub(r'([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7a3])', r' \1 ', line)
            for match in re.finditer(r"\S+", line_seg):
                raw = match.group(0)
                clean = super_clean(raw)
                if clean:
                    script_tokens.append({"text": raw, "clean": clean, "line": line_idx})

    if not script_tokens and not trans_tokens:
        return []

    # Map each transcript token → script line (or -1 for unmatched/improv)
    trans_line_map = [-1] * len(trans_tokens)

    if script_tokens and trans_tokens:
        sm = difflib.SequenceMatcher(
            None,
            [t["clean"] for t in script_tokens],
            [t["clean"] for t in trans_tokens],
            autojunk=False,
        )

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("equal", "replace"):
                for i in range(i2 - i1):
                    si = i1 + i
                    # Proportionally map script range to transcript range
                    ti = j1 + int(i * (j2 - j1) / max(1, i2 - i1))
                    if ti < j2:
                        trans_line_map[ti] = script_tokens[si]["line"]

    # Backward-fill MUST run first! 
    # In BadWords, false starts and retakes precede the final "good" matched take.
    # We want them to attach to the NEXT matched script line.
    last_matched_line = -1
    for ti in range(len(trans_tokens) - 1, -1, -1):
        tok = trans_tokens[ti]
        if trans_line_map[ti] != -1:
            last_matched_line = trans_line_map[ti]
        elif tok.get("status") == "repeat" and last_matched_line != -1:
            trans_line_map[ti] = last_matched_line

    # Forward-fill: acts as a fallback for trailing repeats at the end of the 
    # recording, or edge cases where backward-fill couldn't find a match.
    last_matched_line = -1
    for ti in range(len(trans_tokens)):
        tok = trans_tokens[ti]
        if trans_line_map[ti] != -1:
            last_matched_line = trans_line_map[ti]
        elif tok.get("status") == "repeat" and trans_line_map[ti] == -1 and last_matched_line != -1:
            trans_line_map[ti] = last_matched_line

    # Bridge-fill: absorb isolated unmatched tokens (bad/None) that sit between
    # two groups assigned to the SAME script line. This prevents small gaps 
    # (like a stutter or filler word mid-retake) from splitting a row.
    for ti in range(len(trans_tokens)):
        if trans_line_map[ti] != -1:
            continue
        # Look backward and forward for nearest assigned lines
        prev_line = -1
        for pi in range(ti - 1, -1, -1):
            if trans_line_map[pi] != -1:
                prev_line = trans_line_map[pi]
                break
        next_line = -1
        for ni in range(ti + 1, len(trans_tokens)):
            if trans_line_map[ni] != -1:
                next_line = trans_line_map[ni]
                break
        if prev_line != -1 and prev_line == next_line:
            trans_line_map[ti] = prev_line

    # Build line → transcript tokens mapping (ordered list of groups)
    # We need to preserve transcript ORDER, so we walk through trans_tokens
    # and emit groups: (line_idx_or_None, [tokens])
    groups = []  # list of (line_idx, [token, ...])
    current_line = None
    current_toks = []

    for ti, tok in enumerate(trans_tokens):
        line = trans_line_map[ti]
        if line == current_line:
            current_toks.append(tok)
        else:
            if current_toks:
                groups.append((current_line, current_toks))
            current_line = line
            current_toks = [tok]
    if current_toks:
        groups.append((current_line, current_toks))

    # Track which script lines have been used
    used_script_lines = set()
    for line_idx, _ in groups:
        if line_idx is not None and line_idx != -1:
            used_script_lines.add(line_idx)

    # Build final rows by interleaving script lines and transcript groups
    final_rows = []
    emitted_script_lines = set()

    # Walk through groups in transcript order
    for line_idx, toks in groups:
        # Before emitting this group, emit any earlier unmatched script lines
        if line_idx is not None and line_idx != -1:
            for sl in range(line_idx):
                if sl not in emitted_script_lines and sl not in used_script_lines:
                    final_rows.append({
                        "script_text": script_lines[sl],
                        "transcript_tokens": [],
                        "transcript_text": "",
                        "script_kind": "missing",
                        "transcript_kind": "missing_gap",
                    })
                    emitted_script_lines.add(sl)

        if line_idx is None or line_idx == -1:
            # Improvisation / unmatched transcript
            final_rows.append({
                "script_text": "",
                "transcript_tokens": toks,
                "transcript_text": " ".join(t.get("text", "") for t in toks),
                "script_kind": "improv_gap",
                "transcript_kind": "improv",
            })
        else:
            # Check if this script line already has a row (merge)
            existing = None
            for row in final_rows:
                if row.get("_line_idx") == line_idx and row.get("script_kind") != "missing":
                    existing = row
                    break

            if existing:
                # Merge tokens into existing row
                existing["transcript_tokens"].extend(toks)
                existing["transcript_text"] += " " + " ".join(t.get("text", "") for t in toks)
            else:
                script_line_text = script_lines[line_idx] if line_idx < len(script_lines) else ""
                final_rows.append({
                    "_line_idx": line_idx,
                    "script_text": script_line_text,
                    "transcript_tokens": toks,
                    "transcript_text": " ".join(t.get("text", "") for t in toks),
                    "script_kind": "normal",
                    "transcript_kind": "normal",
                })
                emitted_script_lines.add(line_idx)

    # Append any remaining unmatched script lines at the end
    for sl in range(len(script_lines)):
        if sl not in emitted_script_lines:
            final_rows.append({
                "script_text": script_lines[sl],
                "transcript_tokens": [],
                "transcript_text": "",
                "script_kind": "missing",
                "transcript_kind": "missing_gap",
            })

    # Clean up internal keys
    for row in final_rows:
        row.pop("_line_idx", None)

    # Performance & UI fix: Merge consecutive "missing" rows into a single block.
    # This prevents creating hundreds of QTextEdit widgets for long unspoken segments,
    # which causes severe scroll lag. We join them with \n\n to maintain visual separation.
    merged_rows = []
    for row in final_rows:
        if merged_rows and row["script_kind"] == "missing" and merged_rows[-1]["script_kind"] == "missing":
            merged_rows[-1]["script_text"] += "\n\n" + row["script_text"]
        else:
            merged_rows.append(row)

    return merged_rows
