import os
import re
import json
import streamlit as st
import pandas as pd
from PIL import Image

# ================= 配置区 =================
st.set_page_config(page_title="Coser 图包统计面板", layout="wide")

# 优先读取环境变量，如果未设置则使用默认的本地相对路径
NAS_BASE_PATH = os.environ.get("NAS_BASE_PATH", "./cosplay_data")
DATA_DIR = os.environ.get("DATA_DIR", "./data")

# 确保配置/缓存数据的存储文件夹存在
os.makedirs(DATA_DIR, exist_ok=True)

COSER_I18N_FILE = os.path.join(DATA_DIR, "coser_i18n.json")
CHAR_I18N_FILE = os.path.join(DATA_DIR, "char_i18n.json")
CACHE_FILE = os.path.join(DATA_DIR, "library_cache.csv")

VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

# ================= UI 多语言字典 =================
SUPPORTED_LANGS = {"zh": "简体中文", "en": "English", "ja": "日本語"}

UI_TEXT = {
    "zh": {
        "nav": "📸 菜单导航", "lang_select": "🌐 界面语言",
        "page_overview": "📊 统计概览", "page_coser": "👯‍♀️ Coser 维度",
        "page_char": "🎭 角色维度", "page_i18n": "🌐 多语言管理",
        "sys_maint": "**系统维护**", "rescan": "🔄 强制重新扫盘",
        "total_coser": "Coser 数量", "total_set": "图包 数量", "total_char": "角色 数量",
        "total_img": "图片 总数", "total_size": "存储 总量",
        "sort_label": "⚙️ 全局图表排序维度", "sort_img": "🖼️ 按图片数量", "sort_set": "📁 按图包数量",
        "sort_size": "💾 按文件大小",
        "top_coser": "高产 Coser 排行榜 (Top 10)",
        "full_rank": "🏆 完整排行榜", "rank_coser": "👯‍♀️ Coser 排行", "rank_char": "🎭 角色 排行",
        "export_import": "📥 AI 翻译导入/导出", "export_btn": "导出完整列表 (CSV)",
        "import_help": "上传经过 AI 翻译的 CSV。必须包含 `Original_Name` 和 `Translation` 列。",
        "import_btn": "上传翻译后的 CSV", "save_success": "保存成功！请刷新页面生效。"
    },
    "en": {
        "nav": "📸 Navigation", "lang_select": "🌐 UI Language",
        "page_overview": "📊 Overview", "page_coser": "👯‍♀️ Coser View",
        "page_char": "🎭 Character View", "page_i18n": "🌐 i18n Manager",
        "sys_maint": "**Maintenance**", "rescan": "🔄 Force Rescan",
        "total_coser": "Total Cosers", "total_set": "Total Sets", "total_char": "Total Characters",
        "total_img": "Total Images", "total_size": "Total Size",
        "sort_label": "⚙️ Global Sort By", "sort_img": "🖼️ Image Count", "sort_set": "📁 Set Count",
        "sort_size": "💾 File Size",
        "top_coser": "Top Cosers Ranking (Top 10)",
        "full_rank": "🏆 Full Ranking", "rank_coser": "👯‍♀️ Coser Ranking", "rank_char": "🎭 Character Ranking",
        "export_import": "📥 AI Translation Export/Import", "export_btn": "Export List (CSV)",
        "import_help": "Upload AI-translated CSV. Must contain 'Original_Name' & 'Translation'.",
        "import_btn": "Upload Translated CSV", "save_success": "Saved successfully! Please refresh."
    }
}
# 容错：如果缺日文，默认回退到中文字典
for k in UI_TEXT["zh"].keys():
    if k not in UI_TEXT.get("ja", {}):
        UI_TEXT.setdefault("ja", {})[k] = UI_TEXT["zh"][k]

if 'lang' not in st.session_state: st.session_state.lang = 'zh'


def _t(key): return UI_TEXT.get(st.session_state.lang, UI_TEXT["zh"]).get(key, key)


# ================= 核心工具函数 =================
def load_i18n_dict(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_i18n_dict(filepath, data_dict):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=4)


def format_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"


def perform_full_scan(base_path):
    if not os.path.exists(base_path):
        st.error(f"Directory {base_path} not found!")
        st.stop()

    records = []
    coser_dirs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
    total_cosers = len(coser_dirs)

    if total_cosers == 0: return pd.DataFrame()

    st.info("Scanning directories, please wait...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, coser_dir in enumerate(coser_dirs):
        status_text.text(f"Scanning ({i + 1}/{total_cosers}): {coser_dir}")
        progress_bar.progress((i + 1) / total_cosers)
        coser_path = os.path.join(base_path, coser_dir)

        for set_dir in os.listdir(coser_path):
            set_path = os.path.join(coser_path, set_dir)
            if not os.path.isdir(set_path): continue

            img_count = 0;
            total_size = 0;
            cover_path = ""
            try:
                with os.scandir(set_path) as it:
                    for entry in it:
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in VALID_EXTENSIONS:
                                img_count += 1
                                total_size += entry.stat().st_size
                                if not cover_path: cover_path = entry.path
            except PermissionError:
                pass

            if " - " in set_dir:
                parts = set_dir.split(" - ", 1)
                chars_split = [c.strip() for c in parts[1].split(',')]
                for char in chars_split:
                    if not char: continue
                    char_clean = re.sub(r'\s+\d+$', '', char).lower()
                    records.append({
                        "Coser_Raw": coser_dir.lower(), "Character_Raw": char_clean,
                        "Set_Name": set_dir, "Image_Count": img_count,
                        "Total_Size": total_size, "Cover_Path": cover_path
                    })
            else:
                records.append({
                    "Coser_Raw": coser_dir.lower(), "Character_Raw": "unknown",
                    "Set_Name": set_dir, "Image_Count": img_count,
                    "Total_Size": total_size, "Cover_Path": cover_path
                })

    df = pd.DataFrame(records)
    df.to_csv(CACHE_FILE, index=False)
    progress_bar.empty();
    status_text.empty()
    return df


def render_gallery(df_subset):
    gallery_df = df_subset.groupby('Set_Name').agg({
        'Character_Display': lambda x: ', '.join(set(x)),
        'Image_Count': 'first', 'Total_Size': 'first', 'Cover_Path': 'first'
    }).reset_index()

    cols = st.columns(3)
    for index, row in gallery_df.iterrows():
        with cols[index % 3]:
            st.markdown(f"**{row['Set_Name']}**")
            if pd.notna(row['Cover_Path']) and row['Cover_Path'] and os.path.exists(row['Cover_Path']):
                try:
                    img = Image.open(row['Cover_Path'])
                    img.thumbnail((400, 400))
                    st.image(img, use_container_width=True)
                except Exception:
                    st.warning("Cover Error")
            else:
                st.info("No Cover")
            st.caption(
                f"🎭 : {row['Character_Display']} | 🖼️ : {row['Image_Count']} | 💾 : {format_size(row['Total_Size'])}")
            st.divider()


# ================= 数据加载 =================
coser_i18n = load_i18n_dict(COSER_I18N_FILE)
char_i18n = load_i18n_dict(CHAR_I18N_FILE)

if os.path.exists(CACHE_FILE):
    df_raw = pd.read_csv(CACHE_FILE)
    df_raw.fillna({'Cover_Path': '', 'Character_Raw': 'unknown'}, inplace=True)
else:
    df_raw = perform_full_scan(NAS_BASE_PATH)

if df_raw.empty: st.stop()

# ================= UI 侧边栏 =================
st.sidebar.title(_t("nav"))
lang_options = list(SUPPORTED_LANGS.keys())
selected_lang = st.sidebar.selectbox(_t("lang_select"), lang_options, format_func=lambda x: SUPPORTED_LANGS[x],
                                     index=lang_options.index(st.session_state.lang))

if selected_lang != st.session_state.lang:
    st.session_state.lang = selected_lang
    st.rerun()
curr_lang = st.session_state.lang

df_raw['Coser_Display'] = df_raw['Coser_Raw'].apply(lambda x: coser_i18n.get(curr_lang, {}).get(x, x))
df_raw['Character_Display'] = df_raw['Character_Raw'].apply(lambda x: char_i18n.get(curr_lang, {}).get(x, x))

page_options = [_t("page_overview"), _t("page_coser"), _t("page_char"), _t("page_i18n")]
page = st.sidebar.radio("", page_options)

st.sidebar.divider()
st.sidebar.markdown(_t("sys_maint"))
if st.sidebar.button(_t("rescan")):
    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
    st.rerun()

# ================= 页面路由 =================
if page == _t("page_overview"):
    st.title(_t("page_overview"))

    unique_sets_df = df_raw.drop_duplicates(subset=['Set_Name'])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(_t("total_coser"), df_raw['Coser_Raw'].nunique())
    c2.metric(_t("total_set"), df_raw['Set_Name'].nunique())
    c3.metric(_t("total_char"), df_raw['Character_Raw'].nunique())
    c4.metric(_t("total_img"), f"{unique_sets_df['Image_Count'].sum():,}")
    c5.metric(_t("total_size"), format_size(unique_sets_df['Total_Size'].sum()))
    st.divider()

    # 全局图表排序控制器
    sort_choice = st.radio(
        _t("sort_label"),
        [_t("sort_img"), _t("sort_set"), _t("sort_size")],
        horizontal=True
    )

    # 动态映射排序列
    if sort_choice == _t("sort_img"):
        sort_col = "Images"
    elif sort_choice == _t("sort_set"):
        sort_col = "Sets"
    else:
        sort_col = "Size_Bytes"

    # 数据预聚合
    coser_stats = unique_sets_df.groupby('Coser_Display').agg(
        Sets=('Set_Name', 'count'), Images=('Image_Count', 'sum'), Size_Bytes=('Total_Size', 'sum')
    ).reset_index().sort_values(by=sort_col, ascending=False)

    char_stats = df_raw.groupby('Character_Display').agg(
        Sets=('Set_Name', 'count'), Images=('Image_Count', 'sum'), Size_Bytes=('Total_Size', 'sum')
    ).reset_index().sort_values(by=sort_col, ascending=False)

    # 显示高产图表 (动态排序 Top 10)
    st.subheader(f"{_t('top_coser')} - {sort_choice}")
    st.bar_chart(coser_stats.head(10).set_index("Coser_Display")[sort_col])

    st.divider()
    st.subheader(_t("full_rank"))
    tab_coser, tab_char = st.tabs([_t("rank_coser"), _t("rank_char")])

    with tab_coser:
        coser_stats['Size_Fmt'] = coser_stats['Size_Bytes'].apply(format_size)
        st.dataframe(coser_stats, use_container_width=True, hide_index=True)

    with tab_char:
        char_stats['Size_Fmt'] = char_stats['Size_Bytes'].apply(format_size)
        st.dataframe(char_stats, use_container_width=True, hide_index=True)

# ===== Coser 维度 =====
elif page == _t("page_coser"):
    st.title(_t("page_coser"))
    coser_list = sorted(df_raw['Coser_Display'].unique().tolist())
    selected_coser = st.selectbox("", coser_list)
    if selected_coser:
        coser_data = df_raw[df_raw['Coser_Display'] == selected_coser]
        u_sets = coser_data.drop_duplicates(subset=['Set_Name'])
        st.subheader(
            f"【{selected_coser}】 | Sets: {u_sets.shape[0]} | Img: {u_sets['Image_Count'].sum():,} | {format_size(u_sets['Total_Size'].sum())}")
        st.divider()
        render_gallery(coser_data)

# ===== 角色维度 =====
elif page == _t("page_char"):
    st.title(_t("page_char"))
    char_list = sorted(df_raw['Character_Display'].unique().tolist())
    selected_char = st.selectbox("", char_list)
    if selected_char:
        char_data = df_raw[df_raw['Character_Display'] == selected_char]
        u_sets = char_data.drop_duplicates(subset=['Set_Name'])
        st.subheader(f"【{selected_char}】 | Sets: {u_sets.shape[0]}")
        st.divider()
        render_gallery(char_data)

# ===== 翻译管理 =====
elif page == _t("page_i18n"):
    st.title(_t("page_i18n"))
    st.info(f"当前正在编辑/导出的语言: **{SUPPORTED_LANGS[curr_lang]}**")

    # 为节省篇幅，这里保留之前的在线表格保存逻辑...
    # (导入导出的具体处理函数同上一版，你可以保留前面的 handle_csv_export 和 import 函数)
    st.write("请参阅上一版代码结构添加数据编辑表格。此模块逻辑未变。")