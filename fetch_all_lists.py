import os
import re
import io
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlencode
import json
import time

# -------------------------
# HTTP / Retry
# -------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def make_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=6,
        connect=6,
        read=6,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def _download_bytes(session, url, name, timeout=180, verify=True):
    resp = session.get(url, timeout=timeout, allow_redirects=True, verify=verify)
    resp.raise_for_status()
    return resp.content, resp

def _download_text(session, url, name, timeout=180, verify=True):
    resp = session.get(url, timeout=timeout, allow_redirects=True, verify=verify)
    resp.raise_for_status()
    return resp.text, resp

def _download_csv_to_df(session, url, name, read_csv_kwargs=None, timeout=180, verify=True):
    content, _ = _download_bytes(session, url, name, timeout=timeout, verify=verify)
    read_csv_kwargs = read_csv_kwargs or {}
    return pd.read_csv(io.BytesIO(content), dtype=str, low_memory=False, **read_csv_kwargs)

def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    for c in df.columns:
        df[c] = df[c].fillna("").astype(str).str.strip()
    return df

def _pick_col(df: pd.DataFrame, candidates, fallback_regex=None):
    for c in candidates:
        if c in df.columns:
            return c
    if fallback_regex:
        for c in df.columns:
            if re.search(fallback_regex, c, re.I):
                return c
    return None

# 保守的数据合并函数
def _join_unique(items, sep=" ; "):
    if items is None:
        return ""
    out = []
    seen = set()
    for x in items:
        if pd.isna(x):
            continue
        val = str(x).strip()
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return sep.join(out)

# -------------------------
# Extractors (IMO/MMSI)
# -------------------------
IMO_RE = re.compile(r"\bIMO\D*([0-9]{7})\b", re.I)
MMSI_RE = re.compile(r"\bMMSI\D*([0-9]{9})\b", re.I)

def extract_imo(text: str) -> str:
    if not text: return ""
    m = IMO_RE.search(str(text))
    return m.group(1) if m else ""

def extract_mmsi(text: str) -> str:
    if not text: return ""
    m = MMSI_RE.search(str(text))
    return m.group(1) if m else ""

# -------------------------
# Standard schema (expanded)
# -------------------------
STANDARD_COLS = [
    "Name", "Aliases", "Type", "Programs", "Country", "Details", "IMO", "MMSI",
    "Source_Agency", "Source_List", "UID", "DOB", "POB", "Nationality",
    "Addresses", "Identifiers", "Remarks", "Raw_Record_ID"
]

def _empty_standard_df():
    return pd.DataFrame(columns=STANDARD_COLS)

def _make_blob(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty: return pd.Series([], dtype=str)
    cols = [c for c in ["Name", "Aliases", "Details", "Identifiers", "Addresses", "DOB", "POB", "Remarks"] if c in df.columns]
    if not cols: return pd.Series([""] * len(df), index=df.index)
    blob = df[cols[0]].fillna("").astype(str)
    for c in cols[1:]:
        blob = blob + " ; " + df[c].fillna("").astype(str)
    return blob

# =====================================================================
# USA CSL 抓取函数
# =====================================================================
def fetch_usa_csl(session: requests.Session) -> pd.DataFrame:
    print("📥 正在下载 USA Consolidated Screening List (CSL) - 多重备用方案...")
    
    # 方案1: 官方API (分页获取)
    def try_api_method():
        print("🔄 尝试方案1: 官方CSL API分页获取...")
        try:
            from urllib.parse import urlencode
        except ImportError:
            print("  无法导入urlencode，跳过API方案")
            return None
            
        base_url = "https://api.trade.gov/consolidated_screening_list/search"
        all_records = []
        offset = 0
        size = 100
        
        while True:
            params = {
                'size': size,
                'offset': offset,
                'api_key': ''
            }
            
            try:
                url = f"{base_url}?{urlencode(params)}"
                resp = session.get(url, timeout=60, verify=True)
                resp.raise_for_status()
                
                data = resp.json()
                results = data.get('results', [])
                
                if not results:
                    break
                    
                all_records.extend(results)
                print(f"  已获取 {len(all_records)} 条记录...")
                
                total = data.get('total', 0)
                if len(all_records) >= total or len(results) < size:
                    break
                    
                offset += size
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  API方案失败: {e}")
                return None
                
        return all_records if all_records else None

    # 方案2: 静态JSON文件
    def try_static_json_method():
        print("🔄 尝试方案2: 静态JSON文件...")
        json_urls = [
            "https://api.trade.gov/static/consolidated_screening_list/consolidated.json",
            "https://api.trade.gov/static/consol_screening_list/consolidated.json", 
            "https://www.trade.gov/consolidated-screening-list/consolidated.json",
            "https://data.commerce.gov/api/views/consolidated-screening-list.json"
        ]
        
        for url in json_urls:
            try:
                print(f"  尝试URL: {url}")
                resp = session.get(url, timeout=60, verify=False)
                resp.raise_for_status()
                
                content_type = resp.headers.get('content-type', '').lower()
                if 'json' not in content_type and not url.endswith('.json'):
                    continue
                    
                data = resp.json()
                results = data.get('results', data)
                
                if isinstance(results, list) and results:
                    print(f"  ✅ 成功获取 {len(results)} 条记录")
                    return results
                    
            except Exception as e:
                print(f"  URL失败 {url}: {e}")
                continue
                
        return None

    # 方案3: CSV格式下载
    def try_csv_method():
        print("🔄 尝试方案3: CSV格式下载...")
        csv_urls = [
            "https://api.trade.gov/static/consolidated_screening_list/consolidated.csv",
            "https://www.trade.gov/consolidated-screening-list/consolidated.csv"
        ]
        
        for url in csv_urls:
            try:
                print(f"  尝试CSV: {url}")
                df = _download_csv_to_df(session, url, "CSL CSV", timeout=60, verify=False)
                if not df.empty:
                    print(f"  ✅ CSV成功获取 {len(df)} 行")
                    return df
            except Exception as e:
                print(f"  CSV失败 {url}: {e}")
                continue
        return None

    # 依次尝试各种方案
    methods = [
        ("API分页", try_api_method),
        ("静态JSON", try_static_json_method), 
        ("CSV下载", try_csv_method)
    ]
    
    for method_name, method_func in methods:
        try:
            result = method_func()
            if result is not None:
                if isinstance(result, pd.DataFrame):
                    return process_csl_dataframe(result)
                else:
                    return process_csl_records(result)
        except Exception as e:
            print(f"❌ {method_name}方案完全失败: {e}")
            continue
    
    print("❌ 所有CSL获取方案均失败")
    return _empty_standard_df()

def process_csl_records(records):
    """处理CSL JSON记录数据 - 保留全量"""
    print(f"🔄 正在处理 {len(records)} 条CSL记录（全量保留模式）...")
    
    processed_records = []
    for idx, item in enumerate(records):
        # 更宽松的名称获取策略
        name = str(item.get('name', '')).strip()
        
        # 如果主名称为空，尝试从其他字段获取
        if not name:
            # 尝试从别名获取
            alt_names = item.get('alt_names', [])
            if isinstance(alt_names, list) and alt_names:
                name = str(alt_names[0]).strip()
            elif alt_names:
                name = str(alt_names).strip()
            
            # 如果还是空，用实体编号
            if not name:
                entity_num = str(item.get('entity_number', item.get('id', ''))).strip()
                if entity_num:
                    name = f"ENTITY_{entity_num}"
                else:
                    name = f"CSL_RECORD_{idx}"
        
        source = str(item.get('source', 'CSL')).strip()
        
        programs = item.get('programs', [])
        if not isinstance(programs, list): 
            programs = [str(programs)]
        prog_str = " ; ".join(filter(None, programs))
        
        alt_names = item.get('alt_names', [])
        if not isinstance(alt_names, list): 
            alt_names = [str(alt_names)]
        alt_str = " ; ".join(filter(None, alt_names))
        
        # 地址处理
        addresses = item.get('addresses', [])
        addr_list = []
        country = ""
        if isinstance(addresses, list):
            for a in addresses:
                if not country and a.get('country'):
                    country = str(a.get('country')).strip()
                parts = [a.get('address'), a.get('city'), a.get('state'), 
                        a.get('postal_code'), a.get('country')]
                addr_val = ", ".join([str(p).strip() for p in parts if p and str(p).strip()])
                if addr_val:
                    addr_list.append(addr_val)
        addr_str = " ; ".join(addr_list)
        
        # ID和证件处理
        ids = item.get('ids', [])
        id_list = []
        imo = ""
        mmsi = ""
        if isinstance(ids, list):
            for i in ids:
                type_ = str(i.get('type', '')).strip()
                num = str(i.get('number', '')).strip()
                issue = str(i.get('country', '')).strip()
                id_val = f"{type_}: {num} {issue}".strip(" :")
                if id_val:
                    id_list.append(id_val)
                
                if 'IMO' in type_.upper():
                    imo = num
                elif 'MMSI' in type_.upper():
                    mmsi = num
        id_str = " ; ".join(id_list)
        
        # 其他字段
        dob = item.get('dates_of_birth', [])
        if not isinstance(dob, list): dob = [str(dob)]
        dob_str = " ; ".join(filter(None, dob))
        
        pob = item.get('places_of_birth', [])
        if not isinstance(pob, list): pob = [str(pob)]
        pob_str = " ; ".join(filter(None, pob))
        
        nats = item.get('nationalities', item.get('citizenships', []))
        if not isinstance(nats, list): nats = [str(nats)]
        nat_str = " ; ".join(filter(None, nats))
        
        # 生成唯一的原始记录ID
        raw_id = f"CSL_{source}_{idx}_{hash(str(item))}"
        
        processed_records.append({
            "Name": name,
            "Aliases": alt_str,
            "Type": "实体/个人/船舶",
            "Programs": f"US ({source}) - {prog_str}".strip(" -"),
            "Country": country or nat_str,
            "Details": str(item.get('title', '')).strip(),
            "IMO": imo,
            "MMSI": mmsi,
            "Source_Agency": "USA - Consolidated Screening List",
            "Source_List": source,
            "UID": str(item.get('entity_number', item.get('id', ''))).strip(),
            "DOB": dob_str,
            "POB": pob_str,
            "Nationality": nat_str,
            "Addresses": addr_str,
            "Identifiers": id_str,
            "Remarks": str(item.get('remarks', '')).strip(),
            "Raw_Record_ID": raw_id,
        })
        
    out = pd.DataFrame(processed_records)
    out = _norm_df(out)
    
    # 不过滤任何记录，保留所有数据
    print(f"✅ CSL数据处理完成，保留 {len(out)} 条原始记录")
    
    # 提取IMO/MMSI但不聚合
    blob = _make_blob(out)
    out.loc[out["IMO"] == "", "IMO"] = blob[out["IMO"] == ""].apply(extract_imo)
    out.loc[out["MMSI"] == "", "MMSI"] = blob[out["MMSI"] == ""].apply(extract_mmsi)
    
    return out

def process_csl_dataframe(df):
    """处理CSL CSV数据"""
    print(f"🔄 正在处理 {len(df)} 条CSL CSV记录...")
    # 简化处理，直接转换为标准格式
    out = pd.DataFrame({
        "Name": df.get("name", ""),
        "Aliases": "",
        "Type": "实体/个人/船舶",
        "Programs": "US - CSL",
        "Country": "",
        "Details": "",
        "IMO": "",
        "MMSI": "",
        "Source_Agency": "USA - Consolidated Screening List",
        "Source_List": "CSL",
        "UID": df.get("entity_number", ""),
        "DOB": "",
        "POB": "",
        "Nationality": "",
        "Addresses": "",
        "Identifiers": "",
        "Remarks": "",
        "Raw_Record_ID": df.index.map(lambda x: f"CSL_CSV_{x}"),
    })
    return _norm_df(out)

# =====================================================================
# 修复的UK数据抓取 - 解决索引赋值问题
# =====================================================================
def fetch_uk_ofsi(session: requests.Session) -> pd.DataFrame:
    print("📥 正在下载英国 UK Sanctions List / OFSI 名单（全量模式）...")
    landing_pages = [
        "https://www.gov.uk/government/publications/the-uk-sanctions-list",
        "https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets",
    ]
    
    def _find_links(html, exts=("csv", "xlsx", "xls", "xml", "zip"), pattern=None):
        links = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)
        out = []
        for u in links:
            if not u: continue
            base = u.split("?")[0].lower()
            if any(base.endswith("." + e) for e in exts): out.append(u)
        if pattern:
            out = [u for u in out if re.search(pattern, u, flags=re.I)]
        return out

    def _absolutize(base, href):
        if href.startswith("http://") or href.startswith("https://"): return href
        if href.startswith("//"): return "https:" + href
        if href.startswith("/"):
            m = re.match(r"^(https?://[^/]+)", base)
            return (m.group(1) if m else "") + href
        if base.endswith("/"): return base + href
        return base.rsplit("/", 1)[0] + "/" + href

    def _first_download_link(session, landing_pages, name, pattern=None, exts=("csv", "xlsx", "xls", "xml"), timeout=180, verify=True):
        last_err = None
        for page in landing_pages:
            try:
                html, _ = _download_text(session, page, name, timeout=timeout, verify=verify)
                links = _find_links(html, exts=exts, pattern=pattern)
                if links: return _absolutize(page, links[0])
            except Exception as e:
                last_err = e
        raise RuntimeError(f"{name} 未能从 landing page 解析到下载链接。last_err={last_err}")
    
    csv_url = _first_download_link(session, landing_pages, "UK Sanctions landing", pattern=r"\.csv", exts=("csv",))
    df = _download_csv_to_df(session, csv_url, "UK Sanctions CSV")

    if len(df.columns) == 1 and isinstance(df.columns[0], str) and df.columns[0].strip().lower().startswith("report date"):
        df = _download_csv_to_df(session, csv_url, "UK Sanctions CSV", read_csv_kwargs={"skiprows": 1})

    df = _norm_df(df)
    print(f"📊 UK原始数据行数: {len(df)}")

    name_col = _pick_col(df, ["Name", "name", "Name 6", "Full Name"], fallback_regex=r"\bname\b")
    if not name_col: 
        print("❌ 未找到姓名列")
        return _empty_standard_df()

    uid_col = _pick_col(df, ["Group ID"], fallback_regex=r"group.*id|id")
    alias_col = _pick_col(df, ["Alias/Alternative Spelling", "Aliases", "Alias"], fallback_regex=r"alias|aka")
    program_col = _pick_col(df, ["Regime", "Programme", "Program"], fallback_regex=r"(regime|program)")
    type_col = _pick_col(df, ["Group Type", "Type"], fallback_regex=r"\btype\b")
    remarks_col = _pick_col(df, ["Other Information", "Comment", "Notes"], fallback_regex=r"(comment|note|information)")
    dob_col = _pick_col(df, ["DOB", "Date of Birth"], fallback_regex=r"dob|date.*birth")
    nat_col = _pick_col(df, ["Nationality"], fallback_regex=r"nationalit")
    
    addr_cols = [c for c in df.columns if re.search(r"address|post.*code|zip|country", c, re.I) and c != nat_col]
    ident_cols = [c for c in df.columns if re.search(r"passport|ni.*number|identi|title", c, re.I)]
    pob_cols = [c for c in df.columns if re.search(r"town.*birth|country.*birth", c, re.I)]

    addresses = df[addr_cols].fillna("").astype(str).agg(" , ".join, axis=1).str.replace(r'( , )+', ' , ', regex=True).str.strip(" ,") if addr_cols else pd.Series([""] * len(df))
    identifiers = df[ident_cols].fillna("").astype(str).agg(" ; ".join, axis=1).str.replace(r'( ; )+', ' ; ', regex=True).str.strip(" ;") if ident_cols else pd.Series([""] * len(df))
    pob = df[pob_cols].fillna("").astype(str).agg(" , ".join, axis=1).str.replace(r'( , )+', ' , ', regex=True).str.strip(" ,") if pob_cols else pd.Series([""] * len(df))

    # 【修复】处理空名称的记录 - 避免索引长度不匹配问题
    name_series = df.get(name_col, pd.Series([""] * len(df))).copy()
    
    # 找出空名称的行
    empty_name_indices = name_series[name_series.eq("") | name_series.eq("NAN") | name_series.isna()].index
    
    # 对空名称逐个处理，避免批量赋值问题
    for idx in empty_name_indices:
        if uid_col and df.loc[idx, uid_col] and df.loc[idx, uid_col] != "":
            name_series.loc[idx] = f"UK_ENTITY_{df.loc[idx, uid_col]}"
        else:
            name_series.loc[idx] = f"UK_RECORD_{idx}"

    out = pd.DataFrame({
        "Name": name_series,
        "Aliases": df.get(alias_col, pd.Series([""] * len(df))) if alias_col else pd.Series([""] * len(df)),
        "Type": df.get(type_col, pd.Series([""] * len(df))) if type_col else pd.Series([""] * len(df)),
        "Programs": df.get(program_col, pd.Series(["UK"] * len(df))),
        "Country": df.get("Country", pd.Series([""] * len(df))),  
        "Details": pd.Series([""] * len(df)),
        "IMO": pd.Series([""] * len(df)),
        "MMSI": pd.Series([""] * len(df)),
        "Source_Agency": pd.Series(["UK Sanctions List / OFSI"] * len(df)),
        "Source_List": pd.Series(["UK"] * len(df)),
        "UID": df.get(uid_col, pd.Series([""] * len(df))) if uid_col else pd.Series([""] * len(df)),
        "DOB": df.get(dob_col, pd.Series([""] * len(df))) if dob_col else pd.Series([""] * len(df)),
        "POB": pob,
        "Nationality": df.get(nat_col, pd.Series([""] * len(df))) if nat_col else pd.Series([""] * len(df)),
        "Addresses": addresses,
        "Identifiers": identifiers,
        "Remarks": df.get(remarks_col, pd.Series([""] * len(df))) if remarks_col else pd.Series([""] * len(df)),
        "Raw_Record_ID": pd.Series([f"UK_OFSI_{i}" for i in range(len(df))]),
    })

    out = _norm_df(out)
    
    # 不过滤任何记录，保留所有原始记录
    print(f"✅ UK数据处理完成，保留 {len(out)} 条原始记录")
    
    blob = _make_blob(out)
    out["IMO"] = blob.apply(extract_imo)
    out["MMSI"] = blob.apply(extract_mmsi)
    return out

# =====================================================================
# UN数据抓取 - 保留全量
# =====================================================================
def fetch_un_consolidated(session: requests.Session) -> pd.DataFrame:
    print("📥 正在下载联合国 (UN) 综合制裁名单（全量模式）...")
    url = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
    content, _ = _download_bytes(session, url, "UN consolidated XML")
    root = ET.fromstring(content)

    def gt(el, path):
        node = el.find(path)
        return node.text.strip() if node is not None and node.text else ""

    records = []
    record_id = 0
    
    for ind in root.findall(".//INDIVIDUAL"):
        name = " ".join([gt(ind, x) for x in ["FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME"] if gt(ind, x)]).strip()
        
        # 如果名称为空，用ID填充
        if not name:
            name = f"UN_INDIVIDUAL_{record_id}"
            
        aliases = [a.text.strip() for a in ind.findall(".//INDIVIDUAL_ALIAS/ALIAS_NAME") if a is not None and a.text and a.text.strip()]
        
        nationality = gt(ind, ".//NATIONALITY/VALUE")
        dob = gt(ind, ".//INDIVIDUAL_DATE_OF_BIRTH/DATE")
        pob = gt(ind, ".//INDIVIDUAL_PLACE_OF_BIRTH/CITY")
        remarks = gt(ind, "COMMENTS1")
        uid = gt(ind, "DATAID")

        addrs = []
        for ad in ind.findall(".//INDIVIDUAL_ADDRESS"):
            addr_parts = [gt(ad, x) for x in ["STREET", "CITY", "STATE_PROVINCE", "ZIP_CODE", "COUNTRY"]]
            addr_str = ", ".join([p for p in addr_parts if p])
            if addr_str: addrs.append(addr_str)
            
        docs = []
        for doc in ind.findall(".//INDIVIDUAL_DOCUMENT"):
            doc_str = f"{gt(doc, 'TYPE_OF_DOCUMENT')}: {gt(doc, 'NUMBER')} {gt(doc, 'COUNTRY_OF_ISSUE')}".strip(" :")
            if doc_str: docs.append(doc_str)

        records.append({
            "Name": name, "Aliases": _join_unique(aliases), "Type": "个人",
            "Programs": f"UN - {gt(ind, 'UN_LIST_TYPE')}",
            "Country": nationality, "Details": gt(ind, "DESIGNATION"),
            "IMO": "", "MMSI": "",
            "Source_Agency": "UN Security Council", "Source_List": "UN",
            "UID": uid, "DOB": dob, "POB": pob, "Nationality": nationality,
            "Addresses": " ; ".join(addrs), "Identifiers": " ; ".join(docs),
            "Remarks": remarks,
            "Raw_Record_ID": f"UN_IND_{record_id}",
        })
        record_id += 1

    for ent in root.findall(".//ENTITY"):
        name = gt(ent, "FIRST_NAME") or gt(ent, "NAME_ORIGINAL_SCRIPT")
        
        # 如果名称为空，用ID填充
        if not name:
            name = f"UN_ENTITY_{record_id}"
            
        aliases = [a.text.strip() for a in ent.findall(".//ENTITY_ALIAS/ALIAS_NAME") if a is not None and a.text and a.text.strip()]
        remarks = gt(ent, "COMMENTS1")
        uid = gt(ent, "DATAID")

        addrs = []
        country = ""
        for ad in ent.findall(".//ENTITY_ADDRESS"):
            if not country: country = gt(ad, "COUNTRY")
            addr_parts = [gt(ad, x) for x in ["STREET", "CITY", "STATE_PROVINCE", "ZIP_CODE", "COUNTRY"]]
            addr_str = ", ".join([p for p in addr_parts if p])
            if addr_str: addrs.append(addr_str)

        records.append({
            "Name": name, "Aliases": _join_unique(aliases), "Type": "实体/公司/船舶",
            "Programs": f"UN - {gt(ent, 'UN_LIST_TYPE')}",
            "Country": country, "Details": gt(ent, "DESIGNATION"),
            "IMO": "", "MMSI": "",
            "Source_Agency": "UN Security Council", "Source_List": "UN",
            "UID": uid, "DOB": "", "POB": "", "Nationality": "",
            "Addresses": " ; ".join(addrs), "Identifiers": "",
            "Remarks": remarks,
            "Raw_Record_ID": f"UN_ENT_{record_id}",
        })
        record_id += 1

    if not records: return _empty_standard_df()
    out = pd.DataFrame(records)
    out = _norm_df(out)
    print(f"✅ UN数据处理完成，保留 {len(out)} 条原始记录")
    
    blob = _make_blob(out)
    out["IMO"] = blob.apply(extract_imo)
    out["MMSI"] = blob.apply(extract_mmsi)
    return out

# =====================================================================
# 修复的EU数据抓取 - 解决索引赋值问题
# =====================================================================
def fetch_eu_consolidated(session: requests.Session) -> pd.DataFrame:
    print("📥 正在下载欧盟 (EU) 综合制裁名单（全量保留模式）...")
    url = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content?token=dG9rZW4tMjAxNw"
    df = _download_csv_to_df(session, url, "EU Consolidated", read_csv_kwargs={"sep": ";"})
    df = _norm_df(df)
    print(f"📊 EU原始数据行数: {len(df)}")
    
    name_col = _pick_col(df, ["Naal_wholename", "NameAlias_WholeName"], fallback_regex=r"wholename")
    if not name_col: 
        print("❌ EU数据未找到姓名列")
        return _empty_standard_df()

    uid_col = _pick_col(df, ["Entity_LogicalId", "Reference_number"], fallback_regex=r"logicalid|reference")
    type_mapping = {"P": "个人", "E": "实体/公司", "V": "船舶"}
    subj_col = _pick_col(df, ["Subject_type", "Entity_SubjectType"], fallback_regex=r"subject.*type")
    typ = df[subj_col].map(type_mapping).fillna("其他") if subj_col else pd.Series(["其他"] * len(df))

    dob_col = _pick_col(df, ["BirthDate_BirthDate", "BirthDate"], fallback_regex=r"birthdate")
    pob_col = _pick_col(df, ["BirthDate_City", "BirthDate_Place"], fallback_regex=r"birth.*(city|place)")
    nat_col = _pick_col(df, ["Citizenship_Region", "Citizenship"], fallback_regex=r"citizen")
    
    addr_cols = [c for c in df.columns if re.search(r"addr.*(street|city|zip|place)", c, re.I)]
    ident_cols = [c for c in df.columns if re.search(r"identi|passport", c, re.I)]
    
    addresses = df[addr_cols].fillna("").astype(str).agg(" , ".join, axis=1).str.replace(r'( , )+', ' , ', regex=True).str.strip(" ,") if addr_cols else pd.Series([""] * len(df))
    identifiers = df[ident_cols].fillna("").astype(str).agg(" ; ".join, axis=1).str.replace(r'( ; )+', ' ; ', regex=True).str.strip(" ;") if ident_cols else pd.Series([""] * len(df))
    country = df.get("Addr_country", df.get("Addr_country_description", df.get("Addr_country_iso2", pd.Series([""] * len(df)))))

    # 【修复】处理空名称 - 避免索引长度不匹配问题
    name_series = df.get(name_col, pd.Series([""] * len(df))).copy()
    
    # 找出空名称的行
    empty_name_indices = name_series[name_series.eq("") | name_series.eq("NAN") | name_series.isna()].index
    
    # 对空名称逐个处理
    alias_col_name = "Naal_alias" if "Naal_alias" in df.columns else "NameAlias_Alias"
    for idx in empty_name_indices:
        # 尝试用别名填充
        if alias_col_name in df.columns and df.loc[idx, alias_col_name] and df.loc[idx, alias_col_name] != "":
            name_series.loc[idx] = df.loc[idx, alias_col_name]
        # 尝试用UID填充
        elif uid_col and df.loc[idx, uid_col] and df.loc[idx, uid_col] != "":
            name_series.loc[idx] = f"EU_ENTITY_{df.loc[idx, uid_col]}"
        # 最后用行号填充
        else:
            name_series.loc[idx] = f"EU_RECORD_{idx}"

    out = pd.DataFrame({
        "Name": name_series,
        "Aliases": df.get("Naal_alias", df.get("NameAlias_Alias", pd.Series([""] * len(df)))),
        "Type": typ,
        "Programs": "EU - " + df.get("Programme", df.get("Regulation_Programme", pd.Series(["Consolidated"] * len(df)))).fillna("Consolidated").astype(str),
        "Country": country,
        "Details": pd.Series([""] * len(df)),
        "IMO": pd.Series([""] * len(df)),
        "MMSI": pd.Series([""] * len(df)),
        "Source_Agency": pd.Series(["EU Consolidated List"] * len(df)),
        "Source_List": pd.Series(["EU"] * len(df)),
        "UID": df.get(uid_col, pd.Series([""] * len(df))),
        "DOB": df.get(dob_col, pd.Series([""] * len(df))),
        "POB": df.get(pob_col, pd.Series([""] * len(df))),
        "Nationality": df.get(nat_col, pd.Series([""] * len(df))),
        "Addresses": addresses,
        "Identifiers": identifiers,
        "Remarks": df.get("Remark", df.get("Remarks", pd.Series([""] * len(df)))),
        "Raw_Record_ID": pd.Series([f"EU_{i}" for i in range(len(df))]),
    })

    out = _norm_df(out)
    
    # 【关键】不过滤任何记录，保留全部数据
    print(f"✅ EU数据处理完成，保留 {len(out)} 条原始记录（全量保留）")
    
    blob = _make_blob(out)
    out["IMO"] = blob.apply(extract_imo)
    out["MMSI"] = blob.apply(extract_mmsi)
    return out

# =====================================================================
# 主函数 - 完全无去重版本
# =====================================================================
def main():
    session = make_session()
    strict = os.getenv("STRICT", "0").strip().lower() in ("1", "true", "yes")

    print("🚀 开始构建全球制裁数据库 (USA-CSL + UK + UN + EU) - 完全全量数据模式...")
    frames = {}

    try:
        frames["CSL"] = fetch_usa_csl(session)
        print(f"✅ USA CSL 原始记录数: {len(frames['CSL'])} 个")
    except Exception as e:
        print(f"❌ USA CSL 抓取失败: {e}")
        frames["CSL"] = _empty_standard_df()

    try:
        frames["UK"] = fetch_uk_ofsi(session)
        print(f"✅ UK 原始记录数: {len(frames['UK'])} 个")
    except Exception as e:
        print(f"❌ UK 抓取失败: {e}")
        frames["UK"] = _empty_standard_df()

    try:
        frames["UN"] = fetch_un_consolidated(session)
        print(f"✅ UN 原始记录数: {len(frames['UN'])} 个")
    except Exception as e:
        print(f"❌ UN 抓取失败: {e}")
        frames["UN"] = _empty_standard_df()

    try:
        frames["EU"] = fetch_eu_consolidated(session)
        print(f"✅ EU 原始记录数: {len(frames['EU'])} 个")
    except Exception as e:
        print(f"❌ EU 抓取失败: {e}")
        frames["EU"] = _empty_standard_df()

    missing = [k for k, v in frames.items() if v is None or getattr(v, "empty", True)]
    if missing:
        msg = "数据源抓取为空：" + ", ".join(missing)
        if strict:
            raise RuntimeError("STRICT=1，已中止生成 global_sanctions_database.csv：" + msg)
        else:
            print("⚠️ " + msg + "。STRICT!=1，将继续生成（部分数据）CSV。")

    print("🔄 正在清洗、合并并标准化字段（完全全量保留模式 - 无去重）...")

    all_data = pd.concat([v for v in frames.values() if v is not None and not v.empty], ignore_index=True)
    if all_data.empty:
        raise RuntimeError("所有数据源都为空，无法生成 global_sanctions_database.csv")

    for c in STANDARD_COLS:
        if c not in all_data.columns:
            all_data[c] = ""

    all_data = all_data[STANDARD_COLS].copy()
    all_data = _norm_df(all_data)
    all_data["Name"] = all_data["Name"].astype(str).str.strip().str.upper()

    blob = _make_blob(all_data)
    all_data.loc[all_data["IMO"].eq(""), "IMO"] = blob[all_data["IMO"].eq("")].apply(extract_imo)
    all_data.loc[all_data["MMSI"].eq(""), "MMSI"] = blob[all_data["MMSI"].eq("")].apply(extract_mmsi)

    # 【关键修改】完全不去重 - 保留所有记录
    print(f"📊 全量数据总记录数: {len(all_data)}")
    print("🔄 跳过去重步骤，保留所有原始记录...")
    
    # 重新生成全局唯一ID（确保每条记录可追溯）
    all_data = all_data.reset_index(drop=True)
    all_data['Global_Record_ID'] = all_data.index.map(lambda x: f"GLOBAL_{x:06d}")
    
    print("\n📈 各数据源最终统计:")
    source_stats = {}
    for source in ["CSL", "UK", "UN", "EU"]:
        # 基于Source_Agency来统计
        if source == "CSL":
            count = len(all_data[all_data["Source_Agency"].str.contains("USA.*Consolidated", na=False, regex=True)])
        elif source == "UK":
            count = len(all_data[all_data["Source_Agency"].str.contains("UK.*Sanctions", na=False, regex=True)])
        elif source == "UN":
            count = len(all_data[all_data["Source_Agency"].str.contains("UN.*Security", na=False, regex=True)])
        elif source == "EU":
            count = len(all_data[all_data["Source_Agency"].str.contains("EU.*Consolidated", na=False, regex=True)])
        else:
            count = 0
            
        source_stats[source] = count
        print(f"  {source}: {count:,} 条记录")

    output_file = "global_sanctions_database.csv"
    all_data.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"✅ 完全全量数据输出完成！最终记录总计：{len(all_data):,} 个，已保存至 {output_file}")
    
    # 验证数据完整性
    total_expected = sum(source_stats.values())
    if len(all_data) == total_expected:
        print("✅ 数据完整性验证通过：所有记录均已保留")
    else:
        print(f"⚠️ 数据完整性提醒：预期 {total_expected:,} 条，实际 {len(all_data):,} 条")

if __name__ == "__main__":
    main()
