"""Small, explainable local topic groups. Never calls a model or an external service."""
from __future__ import annotations
import re

VERSION = 1
LABELS = {
    'tech': '科技 / AI', 'music': '音乐', 'entertainment': '影视 / 娱乐',
    'games': '游戏', 'society': '社会 / 观点', 'life': '生活 / 学习',
    'uncategorized': '未分类',
}

# Each concept contributes once. Repeating a word, a quote, or the title does not
# inflate its score; short English terms must be whole words.
RULES = {
    'tech': [(5, r'人工智能|大模型|机器学习|深度学习|\b(?:ai|llm|gpt\w*|chatgpt|openai|claude|deepseek|gemini|codex)\b'),
             (3, r'编程|代码|算法|开源|软件|芯片|显卡|网络安全|漏洞|\b(?:github|python|javascript|coding|programming|software|gpu|ssrf|cybersecurity)\b'),
             (3, r'科技|机器人|自动驾驶|\b(?:technology|robotics|semiconductor)\b')],
    'music': [(5, r'\b(?:kendrick(?: lamar)?|drake|baby keem|keem|kanye(?: west)?|ye|nicki minaj|don toliver|j\.? cole|travis scott|frank ocean|tyler.{0,5}creator|playboi carti|the weeknd)\b|周杰伦|林俊杰|陈奕迅'),
              (4, r'音乐|歌曲|专辑|说唱|演唱会|作曲|编曲|乐器|\b(?:music|song|album|rapper|rap|hip.hop|concert|discography|lyrics|unreleased|snippet|studio sessions|mr\.? morale|big steppers|chromakopia)\b'),
              (2, r'\b(?:tracks?|melody|guitar|piano|singer|grammy|recording)\b|钢琴|吉他|歌手|旋律')],
    'entertainment': [(4, r'电影|影视|电视剧|综艺|明星|演员|动画|动漫|搞笑|\b(?:movie|film|cinema|actor|actress|anime|sitcom|comedy|celebrity|oscars?|netflix)\b'),
                      (2, r'娱乐|票房|导演|\b(?:entertainment|hollywood|box office|tv show)\b')],
    'games': [(5, r'游戏|电竞|主机|\b(?:gaming|videogames?|steam|playstation|xbox|nintendo|minecraft|genshin|elden ring|valorant|gta|baldur)\b|原神|黑神话|塞尔达|赛博朋克|英雄联盟|明日方舟'),
              (2, r'攻略|速通|\b(?:gameplay|speedrun|esports|rpg|fps)\b')],
    'society': [(6, r'巴勒斯坦|以色列|战争|选举|政治|社会问题|\b(?:palestin\w*|israel\w*|war|election|politics|racism|civil rights|congress|geopolitics)\b'),
                (3, r'经济|社会|新闻|历史|哲学|观点|\b(?:economy|society|history|philosophy|democracy)\b')],
    'life': [(4, r'学习方法|知识管理|笔记|读书|阅读|效率|习惯|健身|健康|美食|旅行|摄影|穿搭|\b(?:obsidian|notion|productivity|learning|study|fitness|workout|cooking|recipe|travel|photography|fashion)\b'),
             (3, r'生活|教育|课程|心理|\b(?:lifestyle|education|tutorial|psychology|self.improvement)\b')],
}

def classify(title, body, content=None):
    content = content or {}
    # Authors and image placeholders are not evidence about the post's subject.
    title = re.sub(r'^@[^：:\s]+[：:]\s*', '', title or '')
    body = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', body or '')
    speech = ' '.join(str(s.get('text', '')) for s in content.get('segments', []))[:60000]
    text = re.sub(r'https?://\S+', '', title + '\n' + body[:60000] + '\n' + speech).casefold()
    scores, evidence = {}, {}
    for key, rules in RULES.items():
        hits, score = [], 0
        for weight, pattern in rules:
            match = re.search(pattern, text, re.I)
            if match:
                score += weight
                hits.append(match.group(0))
        scores[key], evidence[key] = score, hits
    ranked = sorted(scores, key=scores.get, reverse=True)
    best = ranked[0]
    ambiguous = scores[best] < 3 or scores[best] == scores[ranked[1]]
    topic = 'uncategorized' if ambiguous else best
    return {'topic': topic, 'source': 'automatic',
            'detail': {'method': 'local_rules', 'version': VERSION,
                       'evidence': evidence[best] if not ambiguous else [],
                       'score': scores[best], 'ambiguous': ambiguous}}
