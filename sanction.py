import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz
from PIL import Image, ImageDraw, ImageFont
import io
import os
from datetime import datetime, timedelta, timezone
import requests
import re

# =========================
# 0) 编号类识别正则
# =========================
IMO_ONLY_RE = re.compile(r"^\d{7}$")
MMSI_ONLY_RE = re.compile(r"^\d{9}$")
IMO_TOKEN_RE = re.compile(r"\bIMO\D*([0-9]{7})\b", re.I)
MMSI_TOKEN_RE = re.compile(r"\bMMSI\D*([0-9]{9})\b", re.I)

def _norm_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()

def _safe_upper(x: str) -> str:
    return (x or "").strip().upper()

def extract_imo(text: str) -> str:
    if not text:
        return ""
    m = IMO_TOKEN_RE.search(str(text))
    return m.group(1) if m else ""

def extract_mmsi(text: str) -> str:
    if not text:
        return ""
    m = MMSI_TOKEN_RE.search(str(text))
    return m.group(1) if m else ""


# =========================
# 1) JPG 生成留痕图片函数 (动态结论评级版)
# =========================
def generate_jpg_report(query, is_hit, total_records, results_df=None, source_counts=None):
    img_width = 1550
    img_height = 1150 if is_hit else 850
    img = Image.new("RGB", (img_width, img_height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("msyh.ttc", 16)
        table_head_font = ImageFont.truetype("msyh.ttc", 18)
        title_font = ImageFont.truetype("msyh.ttc", 28)
        small_font = ImageFont.truetype("msyh.ttc", 14)
    except IOError:
        font = ImageFont.load_default()
        table_head_font = ImageFont.load_default()
        title_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # --- 设置北京时间 (UTC+8) ---
    bj_tz = timezone(timedelta(hours=8))
    query_time_str = datetime.now(bj_tz).strftime('%Y-%m-%d %H:%M:%S')

    draw.text((40, 30), "供应链制裁合规筛查 - 尽职调查留痕报告", fill=(0, 0, 0), font=title_font)
    draw.text((40, 90), f"查询时间: {query_time_str} (GMT+8)", fill=(0, 0, 0), font=font)
    draw.text((40, 130), f"筛查关键词: {query}", fill=(0, 0, 0), font=font)

    footer_y = 550

    # 动态评估并打印系统结论
    if not is_hit or results_df is None or results_df.empty:
        draw.text((40, 190), "系统结论: 未命中,建议放行", fill=(0, 128, 0), font=title_font)
        footer_y = 400
    else:
        max_score = results_df["Score"].max()
        hit_count = len(results_df)

        if max_score == 100:
            conclusion_text = "系统结论: 命中制裁，限制交易，请注意！"
            fill_color = (220, 0, 0)  # 红色
        elif max_score >= 90:
            conclusion_text = f"系统结论: 发现 {hit_count} 条疑似命中，需要进一步排查"
            fill_color = (255, 140, 0)  # 橙色
        elif max_score >= 80:
            conclusion_text = f"系统结论: 发现 {hit_count} 条低度相关，请进一步检查"
            fill_color = (204, 153, 0)  # 深黄色
        else:
            conclusion_text = "系统结论: 未发现疑似命中，相似度均低于设定阈值。建议放行交易。"
            fill_color = (0, 128, 0)  # 绿色

        draw.text((40, 190), conclusion_text, fill=fill_color, font=title_font)

        y_offset = 250

        columns = {
            "Score": {"x": 40, "max_len": 8},
            "Name": {"x": 120, "max_len": 35},
            "Aliases": {"x": 480, "max_len": 25},
            "IMO": {"x": 750, "max_len": 10},
            "MMSI": {"x": 870, "max_len": 12},
            "Source_Agency": {"x": 1010, "max_len": 25},
            "Programs": {"x": 1250, "max_len": 40},
            "Country": {"x": 1420, "max_len": 12},
        }

        draw.rectangle([(30, y_offset), (img_width - 30, y_offset + 35)], fill=(235, 235, 235))
        for col_name, config in columns.items():
            draw.text((config["x"], y_offset + 8), col_name, fill=(50, 50, 50), font=table_head_font)

        y_offset += 45

        def clean_text(text, max_len):
            text = str(text)
            if text.lower() in ["nan", "none", ""]:
                return "无"
            return text[:max_len] + "..." if len(text) > max_len else text

        for _, row in results_df.head(10).iterrows():
            draw.text((columns["Score"]["x"], y_offset), clean_text(row.get("Score", ""), columns["Score"]["max_len"]), fill=(200, 0, 0), font=font)
            draw.text((columns["Name"]["x"], y_offset), clean_text(row.get("Name", ""), columns["Name"]["max_len"]), fill=(0, 0, 0), font=font)
            draw.text((columns["Aliases"]["x"], y_offset), clean_text(row.get("Aliases", ""), columns["Aliases"]["max_len"]), fill=(100, 100, 100), font=font)
            draw.text((columns["IMO"]["x"], y_offset), clean_text(row.get("IMO", ""), columns["IMO"]["max_len"]), fill=(0, 0, 0), font=font)
            draw.text((columns["MMSI"]["x"], y_offset), clean_text(row.get("MMSI", ""), columns["MMSI"]["max_len"]), fill=(0, 0, 0), font=font)
            draw.text((columns["Source_Agency"]["x"], y_offset), clean_text(row.get("Source_Agency", ""), columns["Source_Agency"]["max_len"]), fill=(0, 0, 0), font=font)
            draw.text((columns["Programs"]["x"], y_offset), clean_text(row.get("Programs", ""), columns["Programs"]["max_len"]), fill=(100, 100, 100), font=font)
            draw.text((columns["Country"]["x"], y_offset), clean_text(row.get("Country", ""), columns["Country"]["max_len"]), fill=(0, 0, 0), font=font)

            y_offset += 30
            draw.line([(30, y_offset), (img_width - 30, y_offset)], fill=(230, 230, 230), width=1)
            y_offset += 10

        footer_y = y_offset + 40

    # ------------------ 底部专业审计留痕 ------------------
    draw.line([(30, footer_y), (img_width - 30, footer_y)], fill=(200, 200, 200), width=2)

    footer_y += 20
    draw.text((30, footer_y), "Screening Against (筛查名单机构及数据量)", fill=(100, 100, 100), font=font)
    draw.text((650, footer_y), "Local Sync Time (系统同步时间)", fill=(100, 100, 100), font=font)

    footer_y += 40

    # --- 获取文件的北京时间 ---
    try:
        mtime = os.path.getmtime("global_sanctions_database.csv")
        sync_time_str = datetime.fromtimestamp(mtime, tz=bj_tz).strftime("%Y-%m-%d %H:%M")
    except Exception:
        sync_time_str = datetime.now(bj_tz).strftime("%Y-%m-%d %H:%M")

    if source_counts:
        for agency, count in source_counts.items():
            agency_name = agency if agency else "Other Sources"
            source_text = f"• {agency_name}: {count:,} records"
            draw.text((30, footer_y), source_text, fill=(120, 120, 120), font=small_font)
            draw.text((650, footer_y), f"{sync_time_str} (GMT+8)", fill=(120, 120, 120), font=small_font)
            footer_y += 30

    draw.line([(30, footer_y + 10), (img_width - 30, footer_y + 10)], fill=(200, 200, 200), width=1)

    summary_text = f"Total Valid Records (全库总计实体数量): {total_records:,} Entities"
    draw.text((30, footer_y + 30), summary_text, fill=(50, 50, 50), font=font)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG")
    img_byte_arr.seek(0)
    return img_byte_arr


# =========================
# 2) 页面基本配置
# =========================
st.set_page_config(page_title="制裁筛查与留痕系统", layout="wide")
st.title("🔍 全球制裁合规筛查系统")


# =========================
# 3) 数据读取：支持双源合并
# =========================
GLOBAL_CSV_URL = "https://raw.githubusercontent.com/benkiwsun/sanctions-screening-tool/main/global_sanctions_database.csv"
CHINA_CSV_URL = "https://raw.githubusercontent.com/benkiwsun/sanctions-screening-tool/main/china_mfa_sanctions_database.csv"

@st.cache_data(show_spinner=False)
def load_data():
    def fetch_csv(file_name, url):
        if os.path.exists(file_name):
            try:
                return pd.read_csv(file_name, dtype=str, low_memory=False)
            except Exception:
                pass
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            head = resp.text[:200].lstrip().lower()
            if head.startswith("<!doctype html") or head.startswith("<html"):
                return pd.DataFrame()
            with open(file_name, "wb") as f:
                f.write(resp.content)
            return pd.read_csv(file_name, dtype=str, low_memory=False)
        except Exception:
            return pd.DataFrame()

    with st.spinner("⏳ 正在加载并合并全球及中国制裁数据库..."):
        df_global = fetch_csv("global_sanctions_database.csv", GLOBAL_CSV_URL)
        df_china = fetch_csv("china_mfa_sanctions_database.csv", CHINA_CSV_URL)
        
        frames = [df for df in [df_global, df_china] if not df.empty]
        if not frames:
            st.error("❌ 所有数据库均加载失败，请检查 GitHub 链接。")
            return pd.DataFrame()
            
        combined_df = pd.concat(frames, ignore_index=True)
        return combined_df

df = load_data()

# =========================
# 3.1) 兼容/增强：补齐字段 + 提取数据统计量
# =========================
source_counts = {}

if not df.empty:
    for c in ["Aliases", "Programs", "Country", "Source_Agency", "Type", "Details", "IMO", "MMSI"]:
        if c not in df.columns:
            df[c] = ""

    for c in ["Name", "Aliases", "Programs", "Country", "Source_Agency", "Type", "Details", "IMO", "MMSI"]:
        df[c] = _norm_series(df[c])

    df["Name"] = df["Name"].str.upper()

    blob_for_id = (df["Name"] + " ; " + df["Aliases"] + " ; " + df["Details"]).astype(str)
    df.loc[df["IMO"].eq(""), "IMO"] = blob_for_id[df["IMO"].eq("")].apply(extract_imo)
    df.loc[df["MMSI"].eq(""), "MMSI"] = blob_for_id[df["MMSI"].eq("")].apply(extract_mmsi)

    df["__search_text"] = (df["Name"] + " ; " + df["Aliases"] + " ; " + df["Details"]).astype(str).str.upper()
    
    source_counts = df["Source_Agency"].value_counts().to_dict()
else:
    df = pd.DataFrame(columns=["Name", "Aliases", "Type", "Programs", "Country", "Source_Agency", "Details", "IMO", "MMSI", "__search_text"])

# --- 在页面上显示当前成功加载的数据库源 ---
if source_counts:
    db_status = " | ".join([f"{k}: {v}条" for k, v in source_counts.items()])
    st.caption(f"🟢 当前已加载数据库: {db_status}")

# =========================
# 4) 极简交互界面与智能搜索逻辑
# =========================
search_query = st.text_input(
    "请输入交易对手名称 (支持模糊匹配)：",
    placeholder="例如输入公司英文名、中文简称或船舶 IMO 编号",
)

threshold = st.slider(
    "相似度容忍度 (%)",
    60,
    100,
    90,  # 默认值已修改为 90
    help="设置90%表示允许极轻微的拼写错误。设置100%则必须精确匹配。中文搜索已支持自动包含匹配，无需特意调低此值。",
)

if st.button("开始筛查", type="primary"):
    if df.empty:
        st.error("❌ 数据库为空：请先确认已生成并提供数据库文件。")
    elif not search_query:
        st.warning("请输入筛查关键词。")
    else:
        q = search_query.strip()
        q_up = _safe_upper(q)

        with st.spinner("正在执行智能检索..."):
            if "Name" not in df.columns:
                st.error("❌ 数据库缺少 Name 列，请检查生成的 CSV 格式。")
            else:
                results_df = pd.DataFrame()

                # ==========================================
                # 匹配引擎 1：强逻辑匹配 (专治纯数字与精准包含)
                # ==========================================
                if IMO_ONLY_RE.match(q) and "IMO" in df.columns:
                    hit = df[_norm_series(df["IMO"]) == q]
                    if not hit.empty:
                        results_df = hit.copy()
                        results_df["Score"] = 100.0

                if results_df.empty and MMSI_ONLY_RE.match(q) and "MMSI" in df.columns:
                    hit = df[_norm_series(df["MMSI"]) == q]
                    if not hit.empty:
                        results_df = hit.copy()
                        results_df["Score"] = 100.0

                if results_df.empty:
                    imo = extract_imo(q)
                    if imo and "IMO" in df.columns:
                        hit = df[_norm_series(df["IMO"]) == imo]
                        if not hit.empty:
                            results_df = hit.copy()
                            results_df["Score"] = 100.0

                # ==========================================
                # 匹配引擎 2：名称类的“包含 + 模糊”双轨并发机制
                # ==========================================
                if results_df.empty:
                    matched_rows = []
                    existing_indices = set()

                    # 轨 1：强包含匹配 (Substring Match)
                    mask_contains = df["__search_text"].astype(str).str.contains(re.escape(q_up), na=False)
                    hit_contains = df[mask_contains]

                    if not hit_contains.empty:
                        for idx, row in hit_contains.iterrows():
                            row_copy = row.copy()
                            exact_name = str(row.get("Name", "")).strip()
                            aliases = [a.strip() for a in str(row.get("Aliases", "")).split(";")]
                            if q_up == exact_name or q_up in aliases:
                                row_copy["Score"] = 100.0
                            else:
                                row_copy["Score"] = 99.0
                            matched_rows.append(row_copy)
                            existing_indices.add(idx)

                    # 轨 2：Rapidfuzz 模糊匹配容错
                    candidates = df["__search_text"].astype(str).tolist()
                    matches = process.extract(
                        q_up,
                        candidates,
                        scorer=fuzz.WRatio,
                        limit=15,
                        score_cutoff=threshold,
                    )

                    if matches:
                        for m in matches:
                            row_index = m[2]
                            if row_index not in existing_indices:
                                row_copy = df.iloc[row_index].copy()
                                row_copy["Score"] = round(m[1], 1)
                                matched_rows.append(row_copy)
                                existing_indices.add(row_index)

                    if matched_rows:
                        results_df = pd.DataFrame(matched_rows)
                        results_df = results_df.sort_values(by="Score", ascending=False).head(10)

                # ==========================================
                # 结果展示与动态评级留痕
                # ==========================================
                if not results_df.empty:
                    max_score = results_df["Score"].max()
                    hit_count = len(results_df)

                    # UI界面的动态文字展示逻辑
                    if max_score == 100:
                        st.error("🚨 **系统结论：命中制裁，限制交易，请注意！**")
                        btn_label = "📸 下载 JPG 留痕报告 (命中限制交易)"
                    elif max_score >= 90:
                        st.warning(f"⚠️ **系统结论：发现 {hit_count} 条疑似命中，需要进一步排查**")
                        btn_label = "📸 下载 JPG 留痕报告 (需进一步排查)"
                    elif max_score >= 80:
                        st.info(f"👀 **系统结论：发现 {hit_count} 条低度相关，请进一步检查**")
                        btn_label = "📸 下载 JPG 留痕报告 (低度相关需检查)"
                    else:
                        st.success("✅ **系统结论：未发现疑似命中，相似度均低于设定阈值。建议放行交易。**")
                        btn_label = "📸 下载 JPG 留痕报告 (建议放行)"

                    show_cols = [c for c in ["Score", "Name", "Aliases", "IMO", "MMSI", "Source_Agency", "Programs", "Country"] if c in results_df.columns]
                    st.dataframe(results_df[show_cols], use_container_width=True)

                    jpg_bytes = generate_jpg_report(
                        search_query,
                        is_hit=True,
                        total_records=len(df),
                        results_df=results_df,
                        source_counts=source_counts
                    )
                    st.download_button(
                        label=btn_label,
                        data=jpg_bytes,
                        file_name=f"筛查留痕_{search_query}_检索报告.jpg",
                        mime="image/jpeg",
                    )

                    with st.expander("查看更多信息（Details）"):
                        if "Details" in results_df.columns:
                            st.dataframe(results_df[["Name", "IMO", "MMSI", "Details"]], use_container_width=True)
                        else:
                            st.info("当前数据库不包含 Details 字段。")
                else:
                    st.success("✅ **系统结论：未命中,建议放行**")

                    jpg_bytes = generate_jpg_report(
                        search_query,
                        is_hit=False,
                        total_records=len(df),
                        source_counts=source_counts
                    )
                    st.download_button(
                        label="📸 下载 JPG 留痕报告 (建议放行)",
                        data=jpg_bytes,
                        file_name=f"筛查放行_{search_query}.jpg",
                        mime="image/jpeg",
                    )
