"""小学语文（四年级、六年级）学科种子数据。

公开版本只保留课程目录骨架。

这里只建「学科 → 单元 → 课文 → 考点」骨架，不写题库内容。
教材正文、古诗和原文挖空题由 `data/import_primary_chinese.py` 导入。

为什么年级放成两个 Subject，而不是一个「小学语文」：
用户实际是按年级分别刷题的，章节、页码、题库都是两套；放进同一个学科后，
前端切换年级会变成筛选章节，和现在「切换学科」的使用方式不一致。
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.entities import Chapter, KnowledgePoint, Subject


PRIMARY_CHINESE_VOLUMES = [
    {
        "subject_code": "primary_chinese_g4",
        "subject_name": "小学语文·四年级",
        "exam_name": "小学语文四年级（上册）",
        "description": "人民教育出版社统编版语文四年级上册。教材原文、重点词句和古诗默写题库。",
        "grade": 4,
        "volume": "上册",
        "code": "zh4u",
        "last_page": 130,
        "units": [
            {"name": "第一单元", "page": 1, "lessons": [
                {"name": "1 观潮", "page": 2},
                {"name": "2 繁星", "page": 5},
                {"name": "3* 现代诗二首", "page": 7},
            ]},
            {"name": "第二单元", "page": 13, "lessons": [
                {"name": "4 一个豆荚里的五粒豆", "page": 14},
                {"name": "5 夜间飞行的秘密", "page": 19},
                {"name": "6 方帽子店", "page": 23},
                {"name": "7* 田忌赛马", "page": 28},
            ]},
            {"name": "第三单元", "page": 33, "lessons": [
                {"name": "8 古诗三首", "page": 34, "points": [
                    {"name": "暮江吟", "page": 34},
                    {"name": "题西林壁", "page": 34},
                    {"name": "雪梅", "page": 35},
                ]},
                {"name": "9 爬山虎的脚", "page": 36},
                {"name": "10 蟋蟀的住宅", "page": 39},
            ]},
            {"name": "第四单元", "page": 47, "lessons": [
                {"name": "11 盘古开天地", "page": 48},
                {"name": "12 精卫填海", "page": 50},
                {"name": "13 普罗米修斯", "page": 51},
                {"name": "14* 女娲补天", "page": 54},
            ]},
            {"name": "第五单元", "page": 61, "lessons": [
                {"name": "15 麻雀", "page": 62},
                {"name": "16 爬天都峰", "page": 65},
            ]},
            {"name": "第六单元", "page": 73, "lessons": [
                {"name": "17 长城", "page": 74},
                {"name": "18 颐和园", "page": 77},
                {"name": "19* 秦兵马俑", "page": 80},
            ]},
            {"name": "第七单元", "page": 87, "lessons": [
                {"name": "20 牛和鹅", "page": 88},
                {"name": "21 一只窝囊的大老虎", "page": 93},
                {"name": "22* 陀螺", "page": 98},
                {"name": "23 王戎不取道旁李", "page": 102},
            ]},
            {"name": "第八单元", "page": 107, "lessons": [
                {"name": "24 我将无我，不负人民", "page": 108},
                {"name": "25 为中华之崛起而读书", "page": 110},
                {"name": "26* 延安，我把你追寻", "page": 115},
                {"name": "27 古诗三首", "page": 117, "points": [
                    {"name": "凉州词", "page": 117},
                    {"name": "出塞", "page": 117},
                    {"name": "夏日绝句", "page": 118},
                ]},
            ]},
        ],
    },
    {
        "subject_code": "primary_chinese_g6",
        "subject_name": "小学语文·六年级",
        "exam_name": "小学语文六年级（上册、下册）",
        "description": "人民教育出版社统编版语文六年级上册、下册。教材原文、重点词句和古诗文题库。",
        "grade": 6,
        "volume": "上册",
        "code": "zh6u",
        "last_page": 130,
        "units": [
            {"name": "第一单元", "page": 1, "lessons": [
                {"name": "1 草原", "page": 2},
                {"name": "2 丁香结", "page": 5},
                {"name": "3 古诗词三首", "page": 8, "points": [
                    {"name": "宿建德江", "page": 8},
                    {"name": "六月二十七日望湖楼醉书", "page": 8},
                    {"name": "西江月·夜行黄沙道中", "page": 9},
                ]},
            ]},
            {"name": "第二单元", "page": 13, "lessons": [
                {"name": "4 七律·长征", "page": 14},
                {"name": "5 狼牙山五壮士", "page": 16},
                {"name": "6 开国大典", "page": 19},
                {"name": "7 我的战友邱少云", "page": 24},
            ]},
            {"name": "第三单元", "page": 31, "lessons": [
                {"name": "8 竹节人", "page": 32},
                {"name": "9 宇宙生命之谜", "page": 36},
                {"name": "10* 故宫博物院", "page": 40},
            ]},
            {"name": "第四单元", "page": 49, "lessons": [
                {"name": "11 桥", "page": 50},
                {"name": "12 穷人", "page": 53},
                {"name": "13* 金色的鱼钩", "page": 58},
            ]},
            {"name": "第五单元", "page": 69, "lessons": [
                {"name": "14 灯光", "page": 70},
                {"name": "15 盼", "page": 73},
            ]},
            {"name": "第六单元", "page": 81, "lessons": [
                {"name": "16 只有一个地球", "page": 82},
                {"name": "17* 青山不老", "page": 84},
                {"name": "18* 三黑和土地", "page": 86},
                {"name": "19 古诗三首", "page": 91, "points": [
                    {"name": "浪淘沙（其一）", "page": 91},
                    {"name": "江南春", "page": 91},
                    {"name": "书湖阴先生壁", "page": 92},
                ]},
            ]},
            {"name": "第七单元", "page": 97, "lessons": [
                {"name": "20 文言文二则", "page": 98, "points": [
                    {"name": "两小儿辩日", "page": 98},
                    {"name": "曹冲称象", "page": 99},
                ]},
                {"name": "21 表里的生物", "page": 100},
                {"name": "22* 他们那时候多有趣啊", "page": 103},
            ]},
            {"name": "第八单元", "page": 109, "lessons": [
                {"name": "23 少年闰土", "page": 110},
                {"name": "24 好的故事", "page": 114},
                {"name": "25* 我的伯父鲁迅先生", "page": 117},
                {"name": "26* 有的人—纪念鲁迅有感", "page": 121},
            ]},
        ],
    },    {
        "subject_code": "primary_chinese_g6",
        "subject_name": "小学语文·六年级",
        "exam_name": "小学语文六年级（上册、下册）",
        "description": "人民教育出版社统编版语文六年级上册、下册。教材原文、重点词句和古诗文题库。",
        "grade": 6,
        "volume": "下册",
        "code": "zh6d",
        "last_page": 122,
        "units": [
            {"name": "第一单元", "page": 1, "lessons": [
                {"name": "1 北京的春节", "page": 2},
                {"name": "2 腊八粥", "page": 8},
                {"name": "3 古诗三首", "page": 11, "points": [
                    {"name": "寒食", "page": 11},
                    {"name": "迢迢牵牛星", "page": 11},
                    {"name": "十五夜望月", "page": 12},
                ]},
                {"name": "4* 藏戏", "page": 13},
            ]},
            {"name": "第二单元", "page": 19, "lessons": [
                {"name": "5 鲁滨逊漂流记（节选）", "page": 20},
                {"name": "6* 骑鹅旅行记（节选）", "page": 27},
                {"name": "7* 汤姆·索亚历险记（节选）", "page": 33},
            ]},
            {"name": "第三单元", "page": 43, "lessons": [
                {"name": "8 匆匆", "page": 44},
                {"name": "9 那个星期天", "page": 46},
            ]},
            {"name": "第四单元", "page": 57, "lessons": [
                {"name": "10 古诗三首", "page": 58, "points": [
                    {"name": "马诗", "page": 58},
                    {"name": "石灰吟", "page": 58},
                    {"name": "竹石", "page": 59},
                ]},
                {"name": "11 十六年前的回忆", "page": 60},
                {"name": "12 为人民服务", "page": 64},
                {"name": "13* 董存瑞舍身炸暗堡", "page": 66},
            ]},
            {"name": "第五单元", "page": 79, "lessons": [
                {"name": "14 文言文二则", "page": 80, "points": [
                    {"name": "学弈", "page": 80},
                    {"name": "两小儿辩日", "page": 81},
                ]},
                {"name": "15 真理诞生于一百个问号之后", "page": 82},
                {"name": "16 表里的生物", "page": 87},
                {"name": "17* 他们那时候多有趣啊", "page": 90},
            ]},
            {"name": "古诗词诵读", "page": 111, "lessons": [
                {"name": "采薇（节选）", "page": 111},
                {"name": "送元二使安西", "page": 112},
                {"name": "春夜喜雨", "page": 113},
                {"name": "早春呈水部张十八员外", "page": 114},
                {"name": "江上渔者", "page": 115},
                {"name": "泊船瓜洲", "page": 116},
                {"name": "游园不值", "page": 117},
                {"name": "卜算子·送鲍浩然之浙东", "page": 118},
                {"name": "浣溪沙", "page": 119},
                {"name": "清平乐", "page": 120},
            ]},
        ],
    },
]

# 只用于生成古诗题。教材正文里古诗和注释、拼音混排，直接挖空容易挖到注释，
# 所以古诗单独维护一份干净文本。现代文仍从教材 PDF 原文挖空。
POEMS = {
    ("zh4u", "暮江吟"): {
        "title": "暮江吟", "author": "白居易",
        "lines": ["一道残阳铺水中", "半江瑟瑟半江红", "可怜九月初三夜", "露似真珠月似弓"],
    },
    ("zh4u", "题西林壁"): {
        "title": "题西林壁", "author": "苏轼",
        "lines": ["横看成岭侧成峰", "远近高低各不同", "不识庐山真面目", "只缘身在此山中"],
    },
    ("zh4u", "雪梅"): {
        "title": "雪梅", "author": "卢钺",
        "lines": ["梅雪争春未肯降", "骚人阁笔费评章", "梅须逊雪三分白", "雪却输梅一段香"],
    },
    ("zh4u", "凉州词"): {
        "title": "凉州词", "author": "王翰",
        "lines": ["葡萄美酒夜光杯", "欲饮琵琶马上催", "醉卧沙场君莫笑", "古来征战几人回"],
    },
    ("zh4u", "出塞"): {
        "title": "出塞", "author": "王昌龄",
        "lines": ["秦时明月汉时关", "万里长征人未还", "但使龙城飞将在", "不教胡马度阴山"],
    },
    ("zh4u", "夏日绝句"): {
        "title": "夏日绝句", "author": "李清照",
        "lines": ["生当作人杰", "死亦为鬼雄", "至今思项羽", "不肯过江东"],
    },
    ("zh6u", "宿建德江"): {
        "title": "宿建德江", "author": "孟浩然",
        "lines": ["移舟泊烟渚", "日暮客愁新", "野旷天低树", "江清月近人"],
    },
    ("zh6u", "六月二十七日望湖楼醉书"): {
        "title": "六月二十七日望湖楼醉书", "author": "苏轼",
        "lines": ["黑云翻墨未遮山", "白雨跳珠乱入船", "卷地风来忽吹散", "望湖楼下水如天"],
    },
    ("zh6u", "西江月·夜行黄沙道中"): {
        "title": "西江月·夜行黄沙道中", "author": "辛弃疾",
        "lines": ["明月别枝惊鹊", "清风半夜鸣蝉", "稻花香里说丰年", "听取蛙声一片",
                  "七八个星天外", "两三点雨山前", "旧时茅店社林边", "路转溪桥忽见"],
    },
    ("zh6u", "七律·长征"): {
        "title": "七律·长征", "author": "毛泽东",
        "lines": ["红军不怕远征难", "万水千山只等闲", "五岭逶迤腾细浪", "乌蒙磅礴走泥丸",
                  "金沙水拍云崖暖", "大渡桥横铁索寒", "更喜岷山千里雪", "三军过后尽开颜"],
    },
    ("zh6u", "浪淘沙（其一）"): {
        "title": "浪淘沙（其一）", "author": "刘禹锡",
        "lines": ["九曲黄河万里沙", "浪淘风簸自天涯", "如今直上银河去", "同到牵牛织女家"],
    },
    ("zh6u", "江南春"): {
        "title": "江南春", "author": "杜牧",
        "lines": ["千里莺啼绿映红", "水村山郭酒旗风", "南朝四百八十寺", "多少楼台烟雨中"],
    },
    ("zh6u", "书湖阴先生壁"): {
        "title": "书湖阴先生壁", "author": "王安石",
        "lines": ["茅檐长扫净无苔", "花木成畦手自栽", "一水护田将绿绕", "两山排闼送青来"],
    },    ("zh6d", "寒食"): {
        "title": "寒食", "author": "韩翃",
        "lines": ["春城无处不飞花", "寒食东风御柳斜", "日暮汉宫传蜡烛", "轻烟散入五侯家"],
    },
    ("zh6d", "迢迢牵牛星"): {
        "title": "迢迢牵牛星", "author": "佚名",
        "lines": ["迢迢牵牛星", "皎皎河汉女", "纤纤擢素手", "札札弄机杼",
                  "终日不成章", "泣涕零如雨", "河汉清且浅", "相去复几许",
                  "盈盈一水间", "脉脉不得语"],
    },
    ("zh6d", "十五夜望月"): {
        "title": "十五夜望月", "author": "王建",
        "lines": ["中庭地白树栖鸦", "冷露无声湿桂花", "今夜月明人尽望", "不知秋思落谁家"],
    },
    ("zh6d", "马诗"): {
        "title": "马诗", "author": "李贺",
        "lines": ["大漠沙如雪", "燕山月似钩", "何当金络脑", "快走踏清秋"],
    },
    ("zh6d", "石灰吟"): {
        "title": "石灰吟", "author": "于谦",
        "lines": ["千锤万凿出深山", "烈火焚烧若等闲", "粉骨碎身浑不怕", "要留清白在人间"],
    },
    ("zh6d", "竹石"): {
        "title": "竹石", "author": "郑燮",
        "lines": ["咬定青山不放松", "立根原在破岩中", "千磨万击还坚劲", "任尔东西南北风"],
    },
    ("zh6d", "采薇（节选）"): {
        "title": "采薇（节选）", "author": "佚名",
        "lines": ["昔我往矣", "杨柳依依", "今我来思", "雨雪霏霏"],
    },
    ("zh6d", "送元二使安西"): {
        "title": "送元二使安西", "author": "王维",
        "lines": ["渭城朝雨浥轻尘", "客舍青青柳色新", "劝君更尽一杯酒", "西出阳关无故人"],
    },
    ("zh6d", "春夜喜雨"): {
        "title": "春夜喜雨", "author": "杜甫",
        "lines": ["好雨知时节", "当春乃发生", "随风潜入夜", "润物细无声",
                  "野径云俱黑", "江船火独明", "晓看红湿处", "花重锦官城"],
    },
    ("zh6d", "早春呈水部张十八员外"): {
        "title": "早春呈水部张十八员外", "author": "韩愈",
        "lines": ["天街小雨润如酥", "草色遥看近却无", "最是一年春好处", "绝胜烟柳满皇都"],
    },
    ("zh6d", "江上渔者"): {
        "title": "江上渔者", "author": "范仲淹",
        "lines": ["江上往来人", "但爱鲈鱼美", "君看一叶舟", "出没风波里"],
    },
    ("zh6d", "泊船瓜洲"): {
        "title": "泊船瓜洲", "author": "王安石",
        "lines": ["京口瓜洲一水间", "钟山只隔数重山", "春风又绿江南岸", "明月何时照我还"],
    },
    ("zh6d", "游园不值"): {
        "title": "游园不值", "author": "叶绍翁",
        "lines": ["应怜屐齿印苍苔", "小扣柴扉久不开", "春色满园关不住", "一枝红杏出墙来"],
    },
    ("zh6d", "卜算子·送鲍浩然之浙东"): {
        "title": "卜算子·送鲍浩然之浙东", "author": "王观",
        "lines": ["水是眼波横", "山是眉峰聚", "欲问行人去那边", "眉眼盈盈处"],
    },
    ("zh6d", "浣溪沙"): {
        "title": "浣溪沙", "author": "苏轼",
        "lines": ["山下兰芽短浸溪", "松间沙路净无泥", "萧萧暮雨子规啼",
                  "谁道人生无再少", "门前流水尚能西", "休将白发唱黄鸡"],
    },
    ("zh6d", "清平乐"): {
        "title": "清平乐", "author": "黄庭坚",
        "lines": ["春归何处", "寂寞无行路", "若有人知春去处", "唤取归来同住",
                  "春无踪迹谁知", "除非问取黄鹂", "百啭无人能解", "因风飞过蔷薇"],
    },
}


def norm_name(name: str) -> str:
    """宽松匹配章节名，避免带 / 不带序号时重复建章。"""
    return re.sub(r"^第[一二三四五六七八九十]+[单元章节]\s*", "", name or "").strip()


def _ensure_subject(db: Session, code: str, name: str, exam_name: str, description: str) -> Subject:
    subject = db.query(Subject).filter(Subject.code == code).one_or_none()
    if subject is None:
        subject = Subject(name=name, code=code, exam_name=exam_name, description=description)
        db.add(subject)
        db.flush()
    else:
        subject.name = name
        subject.exam_name = exam_name
        subject.description = description
    return subject


def _next_page(entries: list[dict], idx: int, fallback: int) -> int:
    if idx + 1 < len(entries):
        # 同一页可能放两首古诗（如《宿建德江》《六月二十七日望湖楼醉书》都在 p8）。
        # 直接取 next-1 会得到 p7，页码范围倒挂，正文块就抽不出来。
        return max(entries[idx]["page"], entries[idx + 1]["page"] - 1)
    return fallback


def seed_primary_chinese(db: Session) -> None:
    """幂等创建两个年级的单元、课文和考点。已存在的章节只更新页码/摘要。"""
    for volume_index, volume in enumerate(PRIMARY_CHINESE_VOLUMES):
        subject = _ensure_subject(
            db, volume["subject_code"], volume["subject_name"],
            volume["exam_name"], volume["description"],
        )
        existing = db.query(Chapter).filter(Chapter.subject_id == subject.id).all()
        l1_by_name = {c.name: c for c in existing if c.parent_id is None}

        for unit_index, unit in enumerate(volume["units"]):
            l1_name = f"{volume['grade']}年级{volume['volume']} {unit['name']}"
            l1 = l1_by_name.get(l1_name)
            if l1 is None:
                l1 = Chapter(
                    subject_id=subject.id, name=l1_name, parent_id=None,
                    order_index=volume_index * 100 + unit_index,
                    summary=f"{volume['volume']} {unit['name']}（教材 p{unit['page']}）",
                    page_start=unit["page"],
                )
                db.add(l1)
                db.flush()
                l1_by_name[l1_name] = l1
            else:
                l1.order_index = volume_index * 100 + unit_index
                l1.page_start = unit["page"]

            lessons = unit["lessons"]
            for lesson_i, lesson in enumerate(lessons):
                lesson_end = _next_page(lessons, lesson_i, volume["last_page"])
                if lesson_i + 1 == len(lessons) and unit_index + 1 < len(volume["units"]):
                    lesson_end = min(lesson_end, volume["units"][unit_index + 1]["page"] - 1)

                l2 = next(
                    (c for c in existing if c.parent_id == l1.id and c.name == lesson["name"]), None
                )
                if l2 is None:
                    l2 = Chapter(
                        subject_id=subject.id, name=lesson["name"], parent_id=l1.id,
                        order_index=lesson_i,
                        summary=f"{volume['grade']}年级{volume['volume']} · {lesson['name']}",
                        page_start=lesson["page"],
                    )
                    db.add(l2)
                    db.flush()
                    existing.append(l2)
                else:
                    l2.order_index = lesson_i
                    l2.page_start = lesson["page"]

                points = lesson.get("points") or [{"name": lesson["name"], "page": lesson["page"]}]
                for point_i, point in enumerate(points):
                    point_end = _next_page(points, point_i, lesson_end)
                    kp = db.query(KnowledgePoint).filter(
                        KnowledgePoint.subject_id == subject.id,
                        KnowledgePoint.chapter_id == l2.id,
                        KnowledgePoint.name == point["name"],
                    ).one_or_none()
                    if kp is None:
                        db.add(KnowledgePoint(
                            subject_id=subject.id, chapter_id=l2.id, name=point["name"],
                            description=f"{volume['grade']}年级{volume['volume']} {lesson['name']}",
                            importance=0.6, page_start=point["page"], page_end=point_end,
                            tags=f"primary_chinese:{volume['code']}",
                        ))
                    else:
                        kp.page_start = point["page"]
                        kp.page_end = point_end
                        kp.importance = 0.6
                        kp.tags = f"primary_chinese:{volume['code']}"

        db.commit()


def seed_all(db: Session) -> None:
    """给项目启动用：保留军事理论，再补齐小学语文。"""
    seed_primary_chinese(db)


__all__ = ["POEMS", "PRIMARY_CHINESE_VOLUMES", "seed_all", "seed_primary_chinese"]
