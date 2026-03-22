from __future__ import annotations

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
    "asuna": "明日奈",
    "asuna ichinose": "一之濑明日奈",
    "asuna yuuki": "结城明日奈",
    "asuka langley soryu": "惣流·明日香·兰格雷",
    "astolfo": "阿斯托尔福",
    "atago": "爱宕",
    "aqua": "阿库娅",
    "azusa nakano": "中野梓",
    "baltimore": "巴尔的摩",
    "barbara": "芭芭拉",
    "bb": "BB",
    "belfast": "贝尔法斯特",
    "blair": "布莱尔",
    "boa hancock": "波雅·汉库克",
    "bowsette": "库巴姬",
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
    "cinderella": "灰姑娘",
    "cindy aurum": "辛蒂·奥勒姆",
    "dva": "D.Va",
    "eula": "优菈",
    "eula lawrence": "优菈·劳伦斯",
    "fern": "菲伦",
    "fischl": "菲谢尔",
    "flandre scarlet": "芙兰朵露·斯卡雷特",
    "formidable": "可畏",
    "frieren": "芙莉莲",
    "fubuki": "吹雪",
    "furina": "芙宁娜",
    "futaba sakura": "佐仓双叶",
    "ganyu": "甘雨",
    "gawr gura": "噶呜·古拉",
    "gwen stacy": "格温·史黛西",
    "harley quinn": "哈莉·奎茵",
    "haruhi suzumiya": "凉宫春日",
    "hatsune miku": "初音未来",
    "hestia": "赫斯缇雅",
    "himeno": "姬野",
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
    "jill valentine": "吉尔·瓦伦蒂安",
    "jinx": "金克丝",
    "juri han": "韩蛛俐",
    "kafka": "卡芙卡",
    "kaga": "加贺",
    "kama": "伽摩",
    "kancolle": "舰队Collection",
    "kashima": "鹿岛",
    "kasumi": "霞",
    "keqing": "刻晴",
    "kizuna ai": "绊爱",
    "kobeni higashiyama": "东山小红",
    "kokomi": "珊瑚宫心海",
    "kotori minami": "南小鸟",
    "koyanskaya": "高扬斯卡娅",
    "le malin": "恶毒",
    "lilith aensland": "莉莉丝·安斯兰特",
    "lisa": "丽莎",
    "lola bunny": "罗拉兔",
    "lucy": "露西",
    "lucyna kushinada": "露西娜·库西纳达",
    "mai shiranui": "不知火舞",
    "makima": "玛奇玛",
    "makise kurisu": "牧濑红莉栖",
    "madoka kaname": "鹿目圆",
    "mami tomoe": "巴麻美",
    "marie rose": "玛丽·萝丝",
    "marin kitagawa": "喜多川海梦",
    "megumin": "惠惠",
    "mei": "小美",
    "mikasa ackerman": "三笠·阿克曼",
    "miku hatsune": "初音未来",
    "misa amane": "弥海砂",
    "misato katsuragi": "葛城美里",
    "miyamoto musashi": "宫本武藏",
    "mona": "莫娜",
    "mona megistus": "莫娜·梅吉斯图斯",
    "momo ayase": "绫濑桃",
    "morrigan aensland": "莫莉卡·安斯兰特",
    "minamoto no raikou": "源赖光",
    "mitsuri kanroji": "甘露寺蜜璃",
    "nahida": "纳西妲",
    "nami": "娜美",
    "nazuna nanakusa": "七草荠",
    "nero": "尼禄",
    "nezuko kamado": "灶门祢豆子",
    "nico robin": "妮可·罗宾",
    "nicole demara": "妮可·德玛拉",
    "nilou": "妮露",
    "nobara kugisaki": "钉崎野蔷薇",
    "nozomi": "希",
    "nozomi tojo": "东条希",
    "owari": "尾张",
    "patchouli knowledge": "帕秋莉·诺蕾姬",
    "power": "帕瓦",
    "princess peach": "碧姬公主",
    "princess zelda": "塞尔达公主",
    "raiden shogun": "雷电将军",
    "raikou": "源赖光",
    "ram": "拉姆",
    "raphtalia": "拉芙塔莉雅",
    "raven": "渡鸦",
    "rebecca": "丽贝卡",
    "regensburg": "雷根斯堡",
    "rei ayanami": "绫波丽",
    "reiko holinger": "玲子·霍林格",
    "reimu": "博丽灵梦",
    "reimu hakurei": "博丽灵梦",
    "reisen": "铃仙",
    "remilia": "蕾米莉亚",
    "remilia scarlet": "蕾米莉亚·斯卡雷特",
    "rin tohsaka": "远坂凛",
    "rias gremory": "莉雅丝·吉蒙里",
    "rikka takanashi": "小鸟游六花",
    "rita rossweisse": "丽塔·洛丝薇瑟",
    "robi": "罗宾",
    "robin": "罗宾",
    "ryuuko matoi": "缠流子",
    "ryza": "莱莎",
    "saber": "Saber",
    "sagiri izumi": "和泉纱雾",
    "sakurajima mai": "樱岛麻衣",
    "samus aran": "萨姆斯·阿兰",
    "santa": "圣诞老人",
    "satsuki kiryuuin": "鬼龙院皋月",
    "scathach": "斯卡哈",
    "seraphine": "萨勒芬妮",
    "shadowheart": "影心",
    "shego": "希戈",
    "shenhe": "申鹤",
    "shigure": "时雨",
    "shimakaze": "岛风",
    "shinobu kochou": "胡蝶忍",
    "shizuku kuroe": "黑江雫",
    "shuten douji": "酒吞童子",
    "silver wolf": "银狼",
    "sirius": "天狼星",
    "sparkle": "花火",
    "sucrose": "砂糖",
    "takao": "高雄",
    "taihou": "大凤",
    "tamamo": "玉藻前",
    "tamamo no mae": "玉藻前",
    "tatsumaki": "战栗的龙卷",
    "tifa": "蒂法",
    "tifa lockhart": "蒂法·洛克哈特",
    "triss merigold": "特莉丝·梅莉葛德",
    "tsunade": "纲手",
    "tsunade": "纲手",
    "utena hiiragi": "柊羽衣",
    "vanilla": "香草",
    "velma dinkley": "维尔玛·丁克莱",
    "wednesday addams": "星期三·亚当斯",
    "yamato": "大和",
    "yelan": "夜兰",
    "yae miko": "八重神子",
    "yor forger": "约儿·佛杰",
    "yuudachi": "夕立",
    "yuni": "尤妮",
    "zero two": "02",
    "zelda": "塞尔达",
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
    "nurse": "护士",
    "pe": "",
    "plugsuit": "驾驶服",
    "qipao": "旗袍",
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
    "hane ame": "雨波",
    "jessica nigri": "洁西卡·尼格瑞",
    "rioko凉凉子": "",
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
    return translation if has_chinese(translation) else ""


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


def fill_csv(path: Path, entity: str) -> tuple[int, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else ["key", "raw_name", "translation"]

    worker = translate_coser_name if entity == "cosers" else translate_character_name
    max_workers = 4
    raw_names = [(row.get("raw_name") or "").strip() for row in rows]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        translations = list(executor.map(worker, raw_names))

    translated = 0
    for row, translation in zip(rows, translations, strict=False):
        row["translation"] = translation
        if translation:
            translated += 1

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return translated, len(rows)


def main() -> None:
    targets = [
        (Path("translate/zhcn/characters-zh-CN.csv"), "characters"),
        (Path("translate/zhcn/cosers-zh-CN.csv"), "cosers"),
    ]
    for path, entity in targets:
        translated, total = fill_csv(path, entity)
        print(f"{path}: filled {translated}/{total}")


if __name__ == "__main__":
    main()
