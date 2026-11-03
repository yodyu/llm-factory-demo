"""Context guards for supported metadata and explicitly excluded capabilities."""
import re

NUMBER = r"(?:\d+(?:\.\d+)?|[一二两三四五六七八九十])"
DURATION = re.compile(rf"(?:持续时间\s*(?:为|是|=|：|:)?|(?:持续|连续|维持|保持)(?:异常|超限|升高|高位)?)\s*({NUMBER})\s*(分钟|秒)")
CAPABILITY = r"(?:多主机|多指标|根因(?:定位|分析)?|在线采集|实时采集|连接真实服务器|Isolation\s*Forest|孤立森林|EWMA|LSTM|季节分解|重采样)"
NEGATION = r"(?:不要求|不需要|无需|不做|不要|不涉及|不进行|不使用|不用|不必|不提供|不支持)"
EXCLUDED = re.compile(rf"{NEGATION}\s*(?:进行|提供|实现|支持)?\s*{CAPABILITY}(?:\s*(?:以及|和|及|、|或)\s*{CAPABILITY})*", re.I)
SCOPE = re.compile(r"多主机|多指标|根因|在线采集|实时采集|连接真实服务器")
SAMPLING = re.compile(
    rf"(?:采样间隔\s*(?:为|是|=|：|:)?|每隔|每|采样)\s*({NUMBER})\s*(分钟|秒)"
    r"(?:\s*(?:采样|一(?:个)?点|一次))?|每分钟(?:采样|一(?:个)?点|一次)")


def positive_capabilities(text):
    """Mask only explicit capability exclusions, keeping offsets and other clauses."""
    def mask(match):
        prefix = text[max(0, match.start()-4):match.start()]
        # '不能不做根因定位' is a positive demand, not an exclusion.
        return match.group() if re.search(r"不能$|不得$|并非$", prefix) else ' ' * len(match.group())
    return EXCLUDED.sub(mask, text)


def supported_messages(messages, text):
    """Discard only known false capability complaints; retain unknown limitations."""
    positive = positive_capabilities(text)
    result = []
    for message in messages:
        # Sampling compatibility needs actual attachment metadata and is checked later.
        if re.search(r"重采样|模拟数据当前固定|采样(?:间隔|频率).*(?:固定|不支持|不一致)", message):
            if re.search(r"重采样", positive):
                result.append(message)
            continue
        if SCOPE.search(message) and not SCOPE.search(positive):
            continue
        result.append(message)
    return result


def remove_sampling_duration(extraction, text):
    """A number in a sampling clause cannot establish an alarm duration."""
    if DURATION.search(text):
        return extraction
    return extraction.model_copy(update={'claims': [c for c in extraction.claims if c.key != 'duration_seconds']})


def sampling_issues(turns, source, sampling_seconds):
    declared = []
    for text in turns:
        matches = list(SAMPLING.finditer(text))
        if matches:
            declared = []
            for match in matches:
                raw = match.group(1)
                value = (dict(zip('一二两三四五六七八九十', [1,2,2,3,4,5,6,7,8,9,10])).get(raw)
                         if raw and not raw[0].isdigit() else float(raw) if raw else 1)
                declared.append(value * (60 if match.group(2) == '分钟' or raw is None else 1))
    if len(set(declared)) > 1:
        return ['描述中的采样间隔存在冲突，请明确采用一个间隔。']
    expected = sampling_seconds if source == 'upload' else 60
    if declared and declared[0] != expected:
        target = 'CSV 时间网格' if source == 'upload' else '模拟数据固定间隔'
        return [f'描述中的采样间隔为 {declared[0]:g} 秒，与{target} {expected:g} 秒不一致；不支持重采样。']
    return []
