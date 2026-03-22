from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_translate_entities import normalized_phrase
from scripts.llm_cosplay_translator import (
    LLMTranslationCache,
    build_client_from_env,
    infer_character_name_with_llm,
    infer_coser_name_with_llm,
)


CHARACTER_EXACT = {
    "ahri": "阿狸",
    "bikini": "比基尼",
    "black cat": "黑猫",
    "blue swimsuits": "蓝色泳装",
    "bride": "新娘",
    "bunny": "兔女郎",
    "casual": "私服",
    "cheongsam": "旗袍",
    "chinese dress": "旗袍",
    "christmas": "圣诞",
    "cow": "奶牛",
    "dancer": "舞娘",
    "dress": "礼服",
    "elf": "精灵",
    "fantia collection": "Fantia 合集",
    "gothloli": "哥特萝莉",
    "gym": "健身房",
    "halloween": "万圣节",
    "jk": "",
    "kemono": "兽耳",
    "kimono": "和服",
    "kunoichi": "女忍者",
    "latex": "乳胶",
    "lingerie": "内衣",
    "magical girl": "魔法少女",
    "maid": "女仆",
    "miko": "巫女",
    "monster hunter": "怪物猎人",
    "neko": "猫娘",
    "nurse": "护士",
    "ol": "",
    "pe": "",
    "police": "警察",
    "precure": "光之美少女",
    "princess": "公主",
    "qipao": "旗袍",
    "queen": "女王",
    "rem": "雷姆",
    "rq": "赛车女郎",
    "selfies": "自拍",
    "shielder": "玛修",
    "sonico": "索尼子",
    "succubus": "魅魔",
    "suite collection": "套图合集",
    "suite grand order": "Fate/Grand Order 套图",
    "suite lane": "碧蓝航线套图",
    "super sonico": "超级索尼子",
    "swimsuit": "泳装",
    "valentine": "情人节",
    "vampire": "吸血鬼",
    "witch": "魔女",
    "yukata": "浴衣",
    "zero two": "02",
}

CHARACTER_FULL_NAMES = {
    "2b": "2B",
    "a2": "A2",
    "ada wong": "艾达·王",
    "ai hoshino": "星野爱",
    "akagi": "赤城",
    "akali": "阿卡丽",
    "albedo": "阿贝多",
    "alice": "爱丽丝",
    "alice liddell": "爱丽丝·利德尔",
    "amber": "安柏",
    "anis": "阿妮斯",
    "ann takamaki": "高卷杏",
    "ankha": "安卡",
    "arlecchino": "阿蕾奇诺",
    "artoria pendragon alter": "阿尔托莉雅·潘德拉贡〔Alter〕",
    "asuna": "明日奈",
    "asuna ichinose": "一之濑明日奈",
    "asuna yuuki": "结城明日奈",
    "asuka langley soryu": "惣流·明日香·兰格雷",
    "astolfo": "阿斯托尔福",
    "atago": "爱宕",
    "aqua": "阿库娅",
    "aegir": "埃吉尔",
    "aerith": "爱丽丝",
    "amatsukaze": "天津风",
    "amagi": "天城",
    "amiya": "阿米娅",
    "amelia watson": "阿梅莉亚·华生",
    "aya shameimaru": "射命丸文",
    "azusa nakano": "中野梓",
    "aerith gainsborough": "爱丽丝·盖恩斯巴勒",
    "baltimore": "巴尔的摩",
    "barbara": "芭芭拉",
    "bb": "BB",
    "belfast": "贝尔法斯特",
    "blair": "布莱尔",
    "boa hancock": "波雅·汉库克",
    "boosette": "库巴姬",
    "bowsette": "库巴姬",
    "bradamante": "布拉达曼特",
    "bremerton": "布雷默顿",
    "bulma": "布尔玛",
    "cammy white": "嘉米·怀特",
    "catwoman": "猫女",
    "cc": "C.C.",
    "cheshire": "柴郡",
    "chii": "小叽",
    "chocola": "巧克力",
    "choukai": "鸟海",
    "chun li": "春丽",
    "chun-li": "春丽",
    "cirno": "琪露诺",
    "ciri": "希里",
    "cinderella": "灰姑娘",
    "cynthia": "希罗娜",
    "cindy aurum": "辛蒂·奥勒姆",
    "clownpiece": "克劳恩皮丝",
    "dva": "D.Va",
    "dark magician": "黑魔导士",
    "dark magician girl": "黑魔导女孩",
    "darkness": "达克妮斯",
    "dido": "黛朵",
    "dizzy": "蒂姬",
    "elegg": "艾蕾格",
    "ellen joe": "艾莲·乔",
    "elizabeth liones": "伊丽莎白·里昂妮丝",
    "emilia": "爱蜜莉雅",
    "ereshikigal": "艾蕾什基伽勒",
    "ereshkigal": "艾蕾什基伽勒",
    "eriri": "泽村·斯宾塞·英梨梨",
    "esdeath": "艾斯德斯",
    "eula": "优菈",
    "eula lawrence": "优菈·劳伦斯",
    "evelynn": "伊芙琳",
    "faye valentine": "菲·瓦伦丁",
    "fuyuko mayuzumi": "黛冬优子",
    "fern": "菲伦",
    "fischl": "菲谢尔",
    "flandre scarlet": "芙兰朵露·斯卡雷特",
    "formidable": "可畏",
    "formidable": "可畏",
    "frieren": "芙莉莲",
    "fubuki": "吹雪",
    "furina": "芙宁娜",
    "futaba sakura": "佐仓双叶",
    "ganyu": "甘雨",
    "gawr gura": "噶呜·古拉",
    "gwen": "格温",
    "gwen stacy": "格温·史黛西",
    "hanako urawa": "浦和花子",
    "harley quinn": "哈莉·奎茵",
    "haruhi suzumiya": "凉宫春日",
    "hatsune miku": "初音未来",
    "hestia": "赫斯缇雅",
    "hermione granger": "赫敏·格兰杰",
    "himeno": "姬野",
    "himiko toga": "渡我被身子",
    "himeko": "姬子",
    "higuchi madoka": "樋口圆香",
    "homura akemi": "晓美焰",
    "hk416": "HK416",
    "hinata": "雏田",
    "hinata hyuga": "日向雏田",
    "hitori gotou": "后藤一里",
    "holo": "赫萝",
    "honoka": "穗乃果",
    "hoshimachi suisei": "星街彗星",
    "hoshino ai": "星野爱",
    "houshou marine": "宝钟玛琳",
    "hu tao": "胡桃",
    "hyakumantenbara salome": "壹百满天原莎乐美",
    "ichinose asuna": "一之濑明日奈",
    "illustrious": "光辉",
    "illya": "伊莉雅",
    "implacable": "不挠",
    "ishtar": "伊什塔尔",
    "jabami yumeko": "蛇喰梦子",
    "jane doe": "简·杜",
    "jeanne alter": "黑贞德",
    "jeanne": "贞德",
    "jett": "捷风",
    "jill valentine": "吉尔·瓦伦蒂安",
    "jigoku no fubuki": "地狱吹雪",
    "jinx": "金克丝",
    "juri han": "韩蛛俐",
    "kanade hayami": "速水奏",
    "kafka": "卡芙卡",
    "kaga": "加贺",
    "kangel": "超天酱",
    "kama": "伽摩",
    "kancolle": "舰队Collection",
    "kashima": "鹿岛",
    "kasugano sora": "春日野穹",
    "kasumi": "霞",
    "kasumigaoka utaha": "霞之丘诗羽",
    "keqing": "刻晴",
    "kiara sessyoin": "杀生院祈荒",
    "kim possible": "金姆·可宝",
    "kizuna ai": "绊爱",
    "kobeni": "东山小红",
    "kobeni higashiyama": "东山小红",
    "kokomi": "珊瑚宫心海",
    "kongou": "金刚",
    "kotori minami": "南小鸟",
    "koyanskaya": "高扬斯卡娅",
    "kaguya shinomiya": "四宫辉夜",
    "kuroneko": "黑猫",
    "kurumi tokisaki": "时崎狂三",
    "kyuubei": "丘比",
    "lara croft": "劳拉·克劳馥",
    "le malin": "恶毒",
    "lilith aensland": "莉莉丝·安斯兰特",
    "lisa": "丽莎",
    "lola bunny": "罗拉兔",
    "lucoa": "露科亚",
    "lucy": "露西",
    "lucyna kushinada": "露西娜·库西纳达",
    "lum": "拉姆",
    "lumine": "荧",
    "mai shiranui": "不知火舞",
    "makima": "玛奇玛",
    "makise kurisu": "牧濑红莉栖",
    "madoka kaname": "鹿目圆",
    "mami tomoe": "巴麻美",
    "marcille donato": "玛露希尔·多纳托",
    "marie rose": "玛丽·萝丝",
    "marin kitagawa": "喜多川海梦",
    "marisa kirisame": "雾雨魔理沙",
    "mercy": "天使",
    "megumin": "惠惠",
    "mei": "小美",
    "mikasa ackerman": "三笠·阿克曼",
    "miku": "初音未来",
    "miku hatsune": "初音未来",
    "minato aqua": "湊阿库娅",
    "misty": "小霞",
    "misa amane": "弥海砂",
    "misato katsuragi": "葛城美里",
    "miyamoto musashi": "宫本武藏",
    "mona": "莫娜",
    "mona megistus": "莫娜·梅吉斯图斯",
    "momo ayase": "绫濑桃",
    "morrigan aensland": "莫莉卡·安斯兰特",
    "minamoto no raikou": "源赖光",
    "mitsuri kanroji": "甘露寺蜜璃",
    "motoko kusanagi": "草薙素子",
    "nagato": "长门",
    "nagatoro": "长瀞早濑",
    "nahida": "纳西妲",
    "nami": "娜美",
    "narmaya": "娜露梅",
    "narumea": "娜露梅",
    "nazuna nanakusa": "七草荠",
    "nero": "尼禄",
    "nezuko kamado": "灶门祢豆子",
    "nezuko": "祢豆子",
    "nico robin": "妮可·罗宾",
    "nicole demara": "妮可·德玛拉",
    "nilou": "妮露",
    "nightingale": "南丁格尔",
    "noshiro": "能代",
    "nyotengu": "女天狗",
    "nobara kugisaki": "钉崎野蔷薇",
    "nonomi": "十六夜野宫",
    "nozomi": "希",
    "nozomi tojo": "东条希",
    "ochako uraraka": "丽日御茶子",
    "osakabehime": "刑部姬",
    "owari": "尾张",
    "patchouli knowledge": "帕秋莉·诺蕾姬",
    "perseus": "英仙座",
    "poison ivy": "毒藤女",
    "power": "帕瓦",
    "princess peach": "碧姬公主",
    "princess zelda": "塞尔达公主",
    "prinz eugen": "欧根亲王",
    "psylocke": "灵蝶",
    "raiden shogun": "雷电将军",
    "raikou": "源赖光",
    "ram": "拉姆",
    "rapi": "拉毗",
    "raphtalia": "拉芙塔莉雅",
    "raven": "渡鸦",
    "reika shimohira": "下平玲花",
    "rebecca": "丽贝卡",
    "regensburg": "雷根斯堡",
    "rei ayanami": "绫波丽",
    "reiko holinger": "玲子·霍林格",
    "reimu": "博丽灵梦",
    "reimu hakurei": "博丽灵梦",
    "reze": "蕾塞",
    "reisen": "铃仙",
    "remilia": "蕾米莉亚",
    "remilia scarlet": "蕾米莉亚·斯卡雷特",
    "rio tsukatsuki": "月城柳",
    "rin tohsaka": "远坂凛",
    "rin tosaka": "远坂凛",
    "rias gremory": "莉雅丝·吉蒙里",
    "rikka takanashi": "小鸟游六花",
    "rita rossweisse": "丽塔·洛丝薇瑟",
    "robi": "罗宾",
    "robin": "罗宾",
    "rosaria": "罗莎莉亚",
    "roxy migurdia": "洛琪希·米格路迪亚",
    "ruan mei": "阮·梅",
    "ryuuko matoi": "缠流子",
    "ryza": "莱莎",
    "lynette": "琳妮特",
    "saber": "Saber",
    "saber alter": "黑Saber",
    "sagiri izumi": "和泉纱雾",
    "saint louis": "圣路易斯",
    "sakuya": "十六夜咲夜",
    "sakuya izayoi": "十六夜咲夜",
    "samsung sam": "三星娘",
    "sakurajima mai": "樱岛麻衣",
    "sakamata chloe": "沙花叉克萝耶",
    "samus": "萨姆斯",
    "samus aran": "萨姆斯·阿兰",
    "sanae": "东风谷早苗",
    "santa": "圣诞老人",
    "satsuki kiryuin": "鬼龙院皋月",
    "satsuki kiryuuin": "鬼龙院皋月",
    "scathach": "斯卡哈",
    "seele": "希儿",
    "senritsu no tatsumaki": "战栗的龙卷",
    "senko": "仙狐",
    "seraphine": "萨勒芬妮",
    "shadowheart": "影心",
    "shego": "希戈",
    "shenhe": "申鹤",
    "shinano": "信浓",
    "shimohira reika": "下平玲花",
    "shiroko": "砂狼白子",
    "shigure": "时雨",
    "shimakaze": "岛风",
    "shinobu kochou": "胡蝶忍",
    "shizuku kuroe": "黑江雫",
    "shuten douji": "酒吞童子",
    "silver wolf": "银狼",
    "sirius": "天狼星",
    "snow white": "白雪公主",
    "sparkle": "花火",
    "starfire": "星火",
    "st louis": "圣路易斯",
    "stocking anarchy": "史朵巾",
    "sucrose": "砂糖",
    "suzuya": "铃谷",
    "takao": "高雄",
    "tae takemi": "武见妙",
    "takarada rikka": "宝多六花",
    "taihou": "大凤",
    "tamamo": "玉藻前",
    "tamamo no mae": "玉藻前",
    "tatsumaki": "战栗的龙卷",
    "tifa": "蒂法",
    "tifa lockhart": "蒂法·洛克哈特",
    "tingyun": "停云",
    "tokisaki kurumi": "时崎狂三",
    "tsubasa hanekawa": "羽川翼",
    "ubel": "于贝尔",
    "usada pekora": "兔田佩克拉",
    "uta": "乌塔",
    "triss merigold": "特莉丝·梅莉葛德",
    "tracer": "猎空",
    "tsunade": "纲手",
    "tsunade": "纲手",
    "unicorn": "独角兽",
    "utena hiiragi": "柊羽衣",
    "viper": "毒蛇",
    "venti": "温迪",
    "vanilla": "香草",
    "velma": "维尔玛",
    "velma dinkley": "维尔玛·丁克莱",
    "vi": "蔚",
    "wednesday addams": "星期三·亚当斯",
    "yamato": "大和",
    "yamashiro": "山城",
    "yelan": "夜兰",
    "yae miko": "八重神子",
    "yuzuriha inori": "楪祈",
    "yuno gasai": "我妻由乃",
    "yu mei-ren": "虞美人",
    "yuuka hayase": "早濑优香",
    "yoimiya naganohara": "长野原宵宫",
    "yor": "约儿",
    "yor forger": "约儿·佛杰",
    "yoruichi shihoin": "四枫院夜一",
    "yuudachi": "夕立",
    "yuni": "尤妮",
    "yuyuko": "西行寺幽幽子",
    "zero two": "02",
    "zelda": "塞尔达",
    "ako amau": "天雨亚子",
    "arisu shimada": "岛田爱里寿",
    "ashe": "艾希",
    "ayanami": "绫波",
    "baobhan sith": "妖精骑士崔斯坦",
    "bea": "彩豆",
    "cammy": "嘉米",
    "chika": "藤原千花",
    "chitoge": "桐崎千棘",
    "haruna": "榛名",
    "iori shiromi": "银镜伊织",
    "kallen": "卡莲",
    "katarina": "卡特琳娜",
    "kashino": "鹿乃",
    "kiyohime": "清姬",
    "klara": "克拉拉",
    "kumano": "熊野",
    "little red riding hood": "小红帽",
    "lux": "拉克丝",
    "marnie": "玛俐",
    "meiko shiraki": "白木芽衣子",
    "mount lady": "Mt. Lady",
    "murasame": "村雨",
    "ningguang": "凝光",
    "ooyodo": "大淀",
    "red riding hood": "小红帽",
    "rogue": "罗刹女",
    "rupee": "露菲",
    "rumi usagiyama": "兔山露米",
    "ryuko matoi": "缠流子",
    "spider gwen": "蜘蛛格温",
    "super crown bowser": "库巴姬",
    "topaz": "托帕",
    "yennefer": "叶奈法",
    "yukina himeragi": "姬柊雪菜",
}

CHARACTER_SUFFIXES = {
    "bikini": "比基尼",
    "black cat": "黑猫",
    "black dress": "黑色礼服",
    "black outfit": "黑色服装",
    "bride": "新娘",
    "bunny": "兔女郎",
    "casual": "私服",
    "cat suit": "猫装",
    "cheerleader": "啦啦队",
    "christmas": "圣诞",
    "christmas bunny": "圣诞兔女郎",
    "cyber bikini": "赛博比基尼",
    "dancer": "舞娘",
    "dress": "礼服",
    "fishnet": "渔网袜",
    "halloween": "万圣节",
    "jk": "",
    "kemono": "兽耳",
    "latex": "乳胶",
    "lingerie": "内衣",
    "maid": "女仆",
    "neko": "猫娘",
    "nun": "修女",
    "nurse": "护士",
    "pe": "",
    "police": "警察",
    "plugsuit": "驾驶服",
    "qipao": "旗袍",
    "rq": "赛车女郎",
    "ringfit": "健身环",
    "school uniform": "校服",
    "selfies": "自拍",
    "shibari": "缚绳",
    "sling bikini": "系带比基尼",
    "slingkini": "系带比基尼",
    "succubus": "魅魔",
    "swimsuit": "泳装",
    "various": "",
    "white plugsuit": "白色驾驶服",
}

CHARACTER_SUFFIX_KEYS = sorted(CHARACTER_SUFFIXES, key=len, reverse=True)

COSER_EXACT = {
    "arty huang": "Arty亚缇",
    "blacqkl": "白莉爱吃巧克力",
    "chunmomo": "蠢沫沫",
    "erzuo nisa": "二佐Nisa",
    "hane ame": "雨波",
    "hinata2000": "向日君",
    "hoshilily": "星之迟迟",
    "jessica nigri": "洁西卡·尼格瑞",
    "kisaragiash": "如月灰",
    "kokuhui": "145-yuuhui玉汇",
    "nekokoyoshi": "爆机少女喵小吉",
    "nyako": "喵子nyako",
    "rioko凉凉子": "",
    "xia xia zi": "Natsuko夏夏子",
    "xiaoyukiko": "XIAOYU·小鱼KIKO",
    "xidaidai": "喜呆呆",
    "yaokoututu": "黏黏团子兔",
}


COMMON_ENGLISH_NAMES = {"2b", "a2", "bb", "cc", "dva", "jk", "ol", "pe", "saber", "zero two"}


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def should_write_translation(raw_name: str, translation: str) -> bool:
    if not translation:
        return False
    raw = raw_name.strip()
    if translation.strip() == raw:
        return False
    if normalized_phrase(raw) in COMMON_ENGLISH_NAMES:
        return False
    if not has_chinese(translation):
        return False
    return True


@lru_cache(maxsize=4096)
def translate_character_base(raw_name: str) -> str:
    phrase = normalized_phrase(raw_name)
    if phrase in CHARACTER_FULL_NAMES:
        return CHARACTER_FULL_NAMES[phrase]
    translation = CHARACTER_EXACT.get(phrase, "")
    return translation.strip()


def translate_character_name(raw_name: str) -> str:
    raw_name = raw_name.strip()
    if not raw_name or has_chinese(raw_name):
        return ""

    phrase = normalized_phrase(raw_name)
    if phrase in COMMON_ENGLISH_NAMES:
        return ""
    if phrase in CHARACTER_EXACT:
        translation = CHARACTER_EXACT[phrase]
        return translation if should_write_translation(raw_name, translation) else ""
    if phrase in CHARACTER_FULL_NAMES:
        translation = CHARACTER_FULL_NAMES[phrase]
        return translation if should_write_translation(raw_name, translation) else ""

    for suffix in CHARACTER_SUFFIX_KEYS:
        if not phrase.endswith(suffix):
            continue
        base_raw = raw_name[: len(raw_name) - len(suffix)].strip(" _-/")
        if not base_raw:
            continue
        base_translation = translate_character_base(base_raw)
        if not base_translation:
            continue
        suffix_translation = CHARACTER_SUFFIXES[suffix]
        combined = " ".join(part for part in (base_translation, suffix_translation) if part).strip()
        return combined if should_write_translation(raw_name, combined) else ""

    return ""


@lru_cache(maxsize=1024)
def translate_coser_name(raw_name: str) -> str:
    raw_name = raw_name.strip()
    if not raw_name or has_chinese(raw_name):
        return ""
    phrase = normalized_phrase(raw_name)
    translation = COSER_EXACT.get(phrase, "")
    return translation if should_write_translation(raw_name, translation) else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill zh-CN CSV translations with local heuristics and optional LLM fallback.")
    parser.add_argument(
        "--entity",
        choices=("cosers", "characters", "both"),
        default="both",
        help="Which CSV files to process.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use the configured OpenAI-compatible model for unresolved difficult rows.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel workers for CSV filling.",
    )
    parser.add_argument(
        "--llm-cache",
        default="data/i18n/llm_cache/fill_translate_csv_zhcn.json",
        help="Local cache path for expensive LLM results.",
    )
    return parser.parse_args()


def build_worker(entity: str, use_llm: bool, llm_cache_path: Path):
    base_worker = translate_coser_name if entity == "cosers" else translate_character_name
    if not use_llm:
        return base_worker

    client = build_client_from_env()
    cache = LLMTranslationCache(llm_cache_path)

    def worker(raw_name: str) -> str:
        translation = base_worker(raw_name)
        if translation:
            return translation
        if entity == "cosers":
            translation = infer_coser_name_with_llm(raw_name, client=client, cache=cache)
        else:
            translation = infer_character_name_with_llm(raw_name, client=client, cache=cache)
        return translation if should_write_translation(raw_name, translation) else ""

    return worker


def fill_csv(path: Path, entity: str, worker_count: int, use_llm: bool, llm_cache_path: Path) -> tuple[int, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else ["key", "raw_name", "translation"]

    worker = build_worker(entity, use_llm, llm_cache_path)
    raw_names = [(row.get("raw_name") or "").strip() for row in rows]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        translations = list(executor.map(worker, raw_names))

    translated = 0
    for row, translation in zip(rows, translations, strict=False):
        existing_translation = (row.get("translation") or "").strip()
        row["translation"] = existing_translation or translation
        if row["translation"]:
            translated += 1

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return translated, len(rows)


def main() -> None:
    args = parse_args()
    targets = []
    if args.entity in {"characters", "both"}:
        targets.append((Path("translate/zhcn/characters-zh-CN.csv"), "characters"))
    if args.entity in {"cosers", "both"}:
        targets.append((Path("translate/zhcn/cosers-zh-CN.csv"), "cosers"))
    for path, entity in targets:
        translated, total = fill_csv(
            path,
            entity,
            worker_count=max(1, args.workers),
            use_llm=args.use_llm,
            llm_cache_path=Path(args.llm_cache),
        )
        print(f"{path}: filled {translated}/{total}")


if __name__ == "__main__":
    main()
