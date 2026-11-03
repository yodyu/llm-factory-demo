"""Static presentation styles shared by the workbench and its graph view."""
import streamlit as st


def apply_style():
    # Static CSS only; never interpolate requirements, filenames or model output.
    st.markdown('''<style>
    .block-container{max-width:1240px;padding-top:4rem;padding-bottom:3rem}
    [data-testid="stSidebar"]{background:#fff;border-right:1px solid #E2E8F0}
    [data-testid="stSidebar"][data-collapsed="false"]{width:240px!important;min-width:240px!important;max-width:240px}
    [data-testid="stSidebarContent"]{padding:0!important;gap:8px;scrollbar-gutter:auto}
    [data-testid="stSidebarHeader"]{height:32px;min-height:32px;padding:4px 16px 0;margin:0;width:100%;box-sizing:border-box}
    [data-testid="stSidebarUserContent"]{padding:0 16px 16px;margin:0;width:100%;box-sizing:border-box}
    [data-testid="stSidebar"] .st-key-factory-navigation{min-height:calc(100dvh - 64px);gap:6px}
    [data-testid="stSidebar"] .st-key-nav-brand{gap:0;padding:4px 12px 20px}
    [data-testid="stSidebar"] .st-key-nav-brand p{margin:0;color:#0F172A;font-size:16px;line-height:24px}
    [data-testid="stSidebar"] .st-key-factory-navigation button{height:42px;min-height:42px;padding:0 12px;justify-content:flex-start;text-align:left;gap:10px;border:0!important;background:transparent;color:#0F172A;box-shadow:none;border-radius:8px}
    [data-testid="stSidebar"] .st-key-factory-navigation button p{text-align:left;font-size:14px;font-weight:400;color:inherit}
    [data-testid="stSidebar"] .st-key-factory-navigation button>div{justify-content:flex-start}
    [data-testid="stSidebar"] .st-key-factory-navigation [data-testid="stIconMaterial"]{width:20px;font-size:20px}
    [data-testid="stSidebar"] .st-key-factory-navigation button:hover{background:#F1F5F9}
    [data-testid="stSidebar"] .st-key-factory-navigation button[kind="primary"]{background:#EFF6FF;color:#2563EB}
    [data-testid="stSidebar"] .st-key-factory-navigation button[kind="primary"] p{font-weight:600}
    [data-testid="stSidebar"] .st-key-factory-navigation button:focus-visible{outline:2px solid #93C5FD;outline-offset:2px}
    [data-testid="stSidebar"] .st-key-factory-navigation [data-testid="stLayoutWrapper"]:has(> .st-key-nav-system){margin-top:auto}
    [data-testid="stSidebar"] .st-key-nav-system{gap:8px;padding-top:16px}
    [data-testid="stExpander"],[data-testid="stVerticalBlockBorderWrapper"]{border-color:#E2E8F0;border-radius:10px}
    [data-testid="stMetric"]{background:white;border-color:#E2E8F0;border-radius:10px;padding:12px 16px}
    [data-testid="stMetricValue"]{font-size:1.65rem}
    [data-testid="stCaptionContainer"]{color:#475569}
    [data-testid="stCaptionContainer"] p{color:#475569}
    .st-key-result-sections [role="radiogroup"]{gap:24px;border-bottom:1px solid #E2E8F0}
    .st-key-result-sections label{padding:8px 0 10px!important;margin:0!important;border-bottom:3px solid transparent}
    .st-key-result-sections label:has(input:checked){border-bottom-color:#2563EB}
    .st-key-result-sections label:has(input:checked) p{color:#2563EB;font-weight:600}
    .st-key-result-sections [data-testid="stRadioOption"] > div > div:not([data-testid]){display:none}
    .st-key-result-sections [data-testid="stRadioOption"]:focus-within{outline:2px solid #93C5FD;outline-offset:2px}
    .st-key-task-confirmation,.st-key-result-summary{background:#FFFFFF;border-radius:10px}
    .st-key-result-summary{padding:10px 16px}
    .st-key-result-header h3{font-size:1.65rem!important}
    .st-key-create-inputs{gap:14px}
    .st-key-create-uploads [data-testid="stColumn"]{min-width:0}
    .st-key-create-uploads [data-testid="stFileUploader"]{min-width:0;max-width:100%}
    .st-key-create-uploads [data-testid="stFileUploaderFileName"]{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    h1{font-size:1.9rem!important}h2{font-size:1.5rem!important}h3{font-size:1.2rem!important}
    button{border-radius:8px!important}
    </style>''', unsafe_allow_html=True)
