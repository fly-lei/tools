import streamlit as st
import pandas as pd
import io
import time

def render():
    st.title("📚 跨文件表格字典批量匹配")
    st.markdown("上传海量字典/翻译文件，支持 **单关键词搜索** 或 **导入文件批量搜索**，极速跨文件跨 Sheet 检索目标词汇，并提取相关属性。")
    st.divider()
    # ...(将原 app.py 中工具 6 的剩余所有代码贴到这里)
    search_mode = st.radio("🔍 请选择检索模式",
                           ["A. 单关键词检索 (手动输入)", "B. 批量文件检索 (上传包含待查字段的 Excel/CSV)"],
                           horizontal=True)

    search_targets = []

    st.subheader("1️⃣ 配置查询目标")
    c_q1, c_q2 = st.columns(2)

    if search_mode.startswith("A"):
        with c_q1:
            single_keyword = st.text_input("要搜索的关键词", value="机组无备妥信号")
            if single_keyword.strip():
                search_targets = [single_keyword.strip()]
    else:
        with c_q1:
            query_file = st.file_uploader("上传待查询的文件 (.xlsx, .csv)", type=['xlsx', 'xls', 'csv'], key='q_file')
        with c_q2:
            query_col = st.text_input("待查询文件中的【列名】", value="待查字段")
            query_header = st.number_input("待查询文件的表头所在行 (0=第1行)", value=0, min_value=0, step=1)

        if query_file is not None and query_col:
            try:
                if query_file.name.endswith('.csv'):
                    df_q = pd.read_csv(query_file, header=query_header)
                else:
                    df_q = pd.read_excel(query_file, header=query_header)

                if query_col in df_q.columns:
                    search_targets = df_q[query_col].dropna().astype(str).str.strip().unique().tolist()
                    st.success(f"✅ 成功从文件中提取了 {len(search_targets)} 个不重复的待查询词汇！")
                else:
                    st.error(f"❌ 找不到列名：'{query_col}'，请检查表头所在行是否设置正确。")
            except Exception as e:
                st.error(f"读取查询文件出错: {e}")

    st.divider()

    st.subheader("2️⃣ 配置字典库读取规则")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        zh_col = st.text_input("查找列 (字典表头)", value="title.cn", help="以此列的内容作为搜索目标")
    with c2:
        extract_cols_str = st.text_input("提取列 (支持多列，逗号隔开)", value="title.en, address, offset, bits",
                                         help="匹配成功后，同时提取这些列的内容")
    with c3:
        dict_header = st.number_input("字典表头所在行 (0=第1行)", value=2, min_value=0, step=1)

    c4, c5 = st.columns([3, 1])
    with c4:
        ffill_cols_str = st.text_input("🛠️ 修复合并单元格 (填入列名，逗号隔开)", value="address, offset",
                                       help="自动向下填充这些列的空值，解决 Excel 合并单元格读取为空的问题。")
    with c5:
        st.markdown("<br>", unsafe_allow_html=True)
        exact_match = st.toggle("🎯 开启精确匹配", value=True)

    st.divider()

    st.subheader("3️⃣ 上传字典库文件并执行")
    uploaded_dicts = st.file_uploader("支持同时框选上传多个 .xlsx / .csv 字典文件", type=['xlsx', 'xls', 'csv'],
                                      accept_multiple_files=True)

    if st.button("🚀 开始跨文件批量匹配", type="primary", use_container_width=True):
        if not search_targets:
            st.warning("⚠️ 没有有效的查询词汇，请检查步骤 1！")
        elif not uploaded_dicts:
            st.warning("⚠️ 请先在步骤 3 上传至少一个字典库文件！")
        else:
            extract_cols = [col.strip() for col in extract_cols_str.split(',') if col.strip()]
            ffill_cols = [col.strip() for col in ffill_cols_str.split(',') if col.strip()]

            results = []
            with st.spinner(f"正在疯狂检索 {len(search_targets)} 个目标词汇..."):
                for file in uploaded_dicts:
                    try:
                        if file.name.endswith('.csv'):
                            dfs = {'默认表': pd.read_csv(file, header=dict_header)}
                        else:
                            xls = pd.ExcelFile(file)
                            dfs = {sheet: pd.read_excel(xls, sheet_name=sheet, header=dict_header) for sheet in
                                   xls.sheet_names}

                        for sheet_name, df in dfs.items():
                            if zh_col in df.columns:
                                for fc in ffill_cols:
                                    if fc in df.columns:
                                        df[fc] = df[fc].ffill()

                                df_clean = df.dropna(subset=[zh_col]).copy()
                                df_clean['__search_col__'] = df_clean[zh_col].astype(str).str.strip()

                                for target in search_targets:
                                    if exact_match:
                                        matches = df_clean[df_clean['__search_col__'] == target]
                                    else:
                                        matches = df_clean[
                                            df_clean['__search_col__'].str.contains(target, na=False, regex=False)]

                                    for _, row in matches.iterrows():
                                        item_result = {
                                            '检索词汇 (目标)': target,
                                            '来源字典文件': file.name,
                                            '所在 Sheet 页': sheet_name,
                                            f'查找内容 ({zh_col})': row[zh_col]
                                        }

                                        for col in extract_cols:
                                            if col in df.columns:
                                                item_result[col] = row[col]
                                            else:
                                                item_result[col] = ""

                                        inferred_type = "integer"
                                        bits_val = row['bits'] if 'bits' in df.columns else None
                                        scale_val = row['scale'] if 'scale' in df.columns else None

                                        if pd.notna(bits_val) and str(bits_val).strip() != "":
                                            inferred_type = "enum"
                                        else:
                                            if pd.notna(scale_val) and str(scale_val).strip() != "":
                                                try:
                                                    if float(scale_val) < 1:
                                                        inferred_type = "float"
                                                except ValueError:
                                                    pass

                                        item_result['推断数据类型 (DataType)'] = inferred_type
                                        results.append(item_result)
                    except Exception as e:
                        st.error(f"❌ 解析字典文件 [{file.name}] 时发生异常: {str(e)}")

            if results:
                st.success(f"🎉 匹配圆满成功！共找到了 {len(results)} 条记录。")
                results_df = pd.DataFrame(results)
                st.dataframe(results_df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    results_df.to_excel(writer, index=False, sheet_name='智能匹配提取结果')
                excel_data = output.getvalue()

                st.download_button(
                    label=f"📥 下载智能匹配提取结果.xlsx",
                    data=excel_data,
                    file_name=f"智能提取结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.warning(f"😭 未能找到匹配项。请确认配置是否正确。")

