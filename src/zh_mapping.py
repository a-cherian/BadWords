import zhconv

def to_simplified(text):
    if not text: return ''
    return zhconv.convert(text, 'zh-hans')
