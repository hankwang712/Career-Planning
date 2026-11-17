"""技能文本的规整：同一技能的不同写法（大小写、空格、点号、“熟悉…经验”之类的修饰）归到同一个键。"""
import re
import unicodedata

# 比较用的键只保留字母、数字、汉字和少数有含义的符号（C++ / C# 里的 + 和 #）。
_KEY_DROP = re.compile("[^0-9a-z\u4e00-\u9fff+#]+")
_PREFIX = re.compile("^(?:熟练(?:使用|掌握|运用)?|熟悉|精通|掌握|了解|擅长|具备|具有|拥有|会使用|能够使用|能使用|使用|有)+")
# 只在去掉后剩下的部分本身是已知技能时才采用，所以这里可以列得宽一些。
_SUFFIXES = ("相关开发经验", "开发/部署经验", "项目经验", "工程化经验", "开发经验", "使用经验", "工作经验", "相关经验", "经验",
             "开发能力", "能力", "基础", "技能", "语言", "编程", "开发", "框架", "技术", "工具", "等")
# 组合写法：TensorFlow/PyTorch、Java、Python、C/C++
_SPLIT = re.compile("\\s*(?:/|、|,|，|;|；|&|\\band\\b|及|与|和)\\s*", re.IGNORECASE)


def skill_key(text):
    """比较用的规整键：全角转半角、小写、去掉空白和标点。"""
    value = unicodedata.normalize("NFKC", str(text or "")).casefold().strip()
    return _KEY_DROP.sub("", value)


def phrase_variants(text):
    """去掉“熟悉/掌握”等前缀和“经验/能力”等后缀的候选写法，按从原样到最短的顺序。"""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    variants = [value]
    stripped = _PREFIX.sub("", value).strip()
    if stripped and stripped != value:
        variants.append(stripped)
    for base in list(variants):
        for suffix in _SUFFIXES:
            if base.endswith(suffix) and len(base) > len(suffix):
                variants.append(base[: -len(suffix)].strip())
    seen, ordered = set(), []
    for item in variants:
        key = skill_key(item)
        if key and key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


def split_composite(text):
    """把“TensorFlow/PyTorch”“Java、Python”拆成单项；C/C++ 这类同样拆开。"""
    parts = [part.strip() for part in _SPLIT.split(str(text or "")) if part and part.strip()]
    return parts if len(parts) > 1 else [str(text or "").strip()]


def char_ngrams(key, sizes=(2, 3)):
    """用于字面相近候选召回的字符 n-gram；很短的键直接用自身。"""
    if len(key) <= 2:
        return {key} if key else set()
    grams = set()
    for size in sizes:
        grams.update(key[i:i + size] for i in range(len(key) - size + 1))
    return grams
