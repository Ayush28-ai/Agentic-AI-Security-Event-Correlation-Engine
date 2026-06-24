import os
import time
import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime

API     = os.getenv("SERVER_URL",      "http://soc-server:8000")
LLM_URL = os.getenv("LLM_SERVICE_URL", "http://host.docker.internal:8080")

st.set_page_config(
    page_title="SOC Monitor",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
[data-testid="stSidebar"] { min-width: 210px; max-width: 220px; }
.chat-user {
    background: #1a3a5c; padding: 12px 16px;
    border-radius: 18px 18px 4px 18px;
    margin: 6px 0; color: #e8f4ff;
    border-left: 3px solid #4a90d9;
    font-size: 15px; line-height: 1.5;
}
.chat-bot {
    background: #0f2318; padding: 12px 16px;
    border-radius: 18px 18px 18px 4px;
    margin: 6px 0; color: #d4f5d4;
    border-left: 3px solid #4caf50;
    font-size: 15px; line-height: 1.5;
}
.phi3-tag {
    font-size: 10px; color: #888;
    margin-top: 4px; display: block;
}
.ok   { color: #4caf50; font-weight:600; }
.warn { color: #ff9800; font-weight:600; }
.err  { color: #f44336; font-weight:600; }
</style>
""", unsafe_allow_html=True)

RISK_ICON  = {"CRITICAL":"🔴","HIGH":"🟠","MEDIUM":"🟡","LOW":"🟢"}
RISK_ORDER = {"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1}

for k, v in [("page","📊 Dashboard"),("chat",[])]:
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helpers ────────────────────────────────────────────────

@st.cache_data(ttl=20)
def fetch_incidents():
    try:
        rows = requests.get(f"{API}/incidents", timeout=5).json()
        for r in rows:
            if isinstance(r.get("analysis"), str):
                try:    r["analysis"] = json.loads(r["analysis"])
                except: r["analysis"] = {}
        return rows
    except:
        return []

def worst_risk(lst):
    return max(lst, key=lambda r: RISK_ORDER.get(r,0), default="NONE")

def check_server():
    for _ in range(2):
        try:
            if requests.get(f"{API}/health", timeout=4).status_code == 200:
                return True
        except:
            time.sleep(0.3)
    return False

def check_llm():
    try:
        r = requests.get(f"{LLM_URL}/health", timeout=3)
        if r.status_code == 200:
            return r.json().get("ready", True)
    except:
        pass
    return False

def build_context():
    fresh = fetch_incidents()
    if not fresh:
        return ""
    devs   = list({i["device_name"] for i in fresh})
    high   = [i for i in fresh if i["risk_level"] in ("CRITICAL","HIGH")]
    latest = fresh[0]
    la     = latest.get("analysis", {})
    lines = [
        f"Devices: {', '.join(devs)} | Total incidents: {len(fresh)}",
        f"HIGH/CRITICAL count: {len(high)}",
        f"Latest: [{latest['risk_level']}] {latest['device_name']} "
        f"CPU:{latest.get('ops_cpu',0):.0f}% RAM:{latest.get('ops_memory',0):.0f}%",
        f"Summary: {la.get('summary','')[:120]}",
    ]
    if high:
        h  = high[0]
        ha = h.get("analysis", {})
        lines.append(
            f"Top alert: [{h['risk_level']}] {h['device_name']} — "
            f"{ha.get('summary','')[:100]}"
        )
    return "\n".join(lines)[:600]


def call_phi3(question: str, context: str = "") -> tuple:
    try:
        r = requests.post(
            f"{LLM_URL}/ask",
            json={"question": question, "context": context, "mode": "analyst"},
            timeout=90
        )
        if r.status_code == 200:
            data   = r.json()
            ans    = data.get("answer","").strip()
            source = data.get("source","")
            if ans and len(ans) > 5 and source == "phi3":
                return ans, True
    except requests.exceptions.Timeout:
        print("⚠️  Phi-3 timed out")
    except Exception as e:
        print(f"⚠️  Phi-3 error: {e}")
    return "", False


# ── Sidebar ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🛡️ SOC Monitor")
    st.divider()

    for p in ["📊 Dashboard","🤖 LLM Analyst","🔧 Device Controls"]:
        active = st.session_state.page == p
        if st.button(p, key=f"nav_{p}", use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state.page = p
            st.rerun()

    st.divider()

    if check_server():
        st.markdown('<span class="ok">● Server online</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="err">● Server offline</span>',
                    unsafe_allow_html=True)

    if check_llm():
        st.markdown('<span class="ok">● Phi-3 online</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="warn">● Phi-3 offline</span>',
                    unsafe_allow_html=True)

    st.divider()
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

page      = st.session_state.page
incidents = fetch_incidents()
devices   = list({i["device_name"] for i in incidents}) if incidents else []


# ══════════════════════════════════════════════════════════
# PAGE 1 — DASHBOARD
# ══════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("🛡️ SOC Monitor Dashboard")

    if not incidents:
        st.info("No incidents yet. Start the PC agent:")
        st.code("SERVER_URL=http://localhost:8000 python3 agent/pc_agent.py")
        st.stop()

    total     = len(incidents)
    crit_high = sum(1 for i in incidents
                    if i["risk_level"] in ("CRITICAL","HIGH"))
    avg_cpu   = round(sum(i.get("ops_cpu",0) for i in incidents)/total, 1)
    avg_mem   = round(sum(i.get("ops_memory",0) for i in incidents)/total, 1)

    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Devices",        len(devices))
    k2.metric("Total",          total)
    k3.metric("Critical/High",  crit_high,
              delta=f"+{crit_high}" if crit_high else None,
              delta_color="inverse")
    k4.metric("Avg CPU",        f"{avg_cpu}%")
    k5.metric("Avg RAM",        f"{avg_mem}%")
    st.divider()

    st.subheader("Risk distribution")
    rc = {}
    for i in incidents:
        rc[i["risk_level"]] = rc.get(i["risk_level"],0)+1
    c1,c2,c3,c4 = st.columns(4)
    for col, risk in zip([c1,c2,c3,c4],["CRITICAL","HIGH","MEDIUM","LOW"]):
        col.metric(f"{RISK_ICON.get(risk,'')} {risk}", rc.get(risk,0))
    st.divider()

    st.subheader("Device status")
    dcols = st.columns(min(len(devices),4))
    for col, dev in zip(dcols, devices):
        di   = [i for i in incidents if i["device_name"]==dev]
        lt   = di[0] if di else {}
        risk = lt.get("risk_level","UNKNOWN")
        with col:
            st.markdown(f"**{RISK_ICON.get(risk,'⚪')} {dev}**")
            st.caption(f"{risk} | {len(di)} incidents")
            st.progress(min(int(lt.get("ops_cpu",0)),100),
                        text=f"CPU {lt.get('ops_cpu',0):.0f}%")
            st.progress(min(int(lt.get("ops_memory",0)),100),
                        text=f"RAM {lt.get('ops_memory',0):.0f}%")
    st.divider()

    st.subheader("Incident feed")
    cf1,cf2 = st.columns(2)
    f_risk = cf1.multiselect("Risk",
        ["CRITICAL","HIGH","MEDIUM","LOW"],
        default=["CRITICAL","HIGH","MEDIUM","LOW"])
    f_dev = cf2.selectbox("Device", ["All"]+devices)

    filtered = [i for i in incidents
                if i["risk_level"] in f_risk
                and (f_dev=="All" or i["device_name"]==f_dev)]

    for row in filtered[:25]:
        a    = row.get("analysis",{})
        risk = row.get("risk_level","UNKNOWN")
        with st.expander(
            f"{RISK_ICON.get(risk,'⚪')} [{risk}]  "
            f"**{row['device_name']}**  —  {row['timestamp'][:19]}"
        ):
            t1,t2,t3 = st.tabs(["📋 Analysis","📊 Metrics","🔧 Actions"])
            with t1:
                st.write(f"**Summary:** {a.get('summary','N/A')}")
                st.write(f"**Root cause:** {a.get('root_cause','N/A')}")
                st.write(f"**Confidence:** {a.get('confidence','N/A')}")
                st.write(f"**Entity:** {a.get('affected_entity','N/A')}")
            with t2:
                m1,m2,m3 = st.columns(3)
                m1.metric("CPU",  f"{row.get('ops_cpu',0):.1f}%")
                m2.metric("RAM",  f"{row.get('ops_memory',0):.1f}%")
                m3.metric("Disk", f"{row.get('ops_disk',0):.1f}%")
            with t3:
                for act in a.get("recommended_actions",[]):
                    st.write(f"→ {act}")
                st.divider()
                for loc in a.get("where_to_fix",[]):
                    st.write(f"📍 {loc}")

    st.divider()
    st.subheader("Trends")
    ch1,ch2 = st.columns(2)
    df = pd.DataFrame([{
        "time": i["timestamp"][:19], "device": i["device_name"],
        "cpu":  i.get("ops_cpu",0),  "mem":   i.get("ops_memory",0)
    } for i in filtered])
    if not df.empty:
        with ch1:
            st.caption("CPU %")
            try:
                st.line_chart(df.pivot_table(
                    index="time",columns="device",values="cpu",aggfunc="mean"))
            except:
                st.line_chart(df.set_index("time")[["cpu"]])
        with ch2:
            st.caption("RAM %")
            try:
                st.line_chart(df.pivot_table(
                    index="time",columns="device",values="mem",aggfunc="mean"))
            except:
                st.line_chart(df.set_index("time")[["mem"]])


# ══════════════════════════════════════════════════════════
# PAGE 2 — LLM ANALYST
# ══════════════════════════════════════════════════════════
elif page == "🤖 LLM Analyst":
    st.title("🤖 SOC AI Analyst")

    llm_live = check_llm()

    cs1,cs2,cs3 = st.columns(3)
    cs1.markdown(
        f"**Engine:** {'🟢 Phi-3 LLM' if llm_live else '🟡 Rule-based'}"
    )
    cs2.markdown(f"**Incidents:** {len(incidents)}")
    cs3.markdown(f"**Devices:** {len(devices)}")
    st.divider()

    def answer(question: str):
        fresh = fetch_incidents()
        devs  = list({i["device_name"] for i in fresh}) if fresh else []
        ql    = question.lower().strip()

        def phi3(q: str = question):
            if not check_llm():
                return None, None
            ctx = build_context()
            ans, ok = call_phi3(q, ctx)
            return (ans, "phi3") if ok else (None, None)

        # ── 1. Identity — exact phrases only ───────────────
        # CHANGE: removed broad words like "about you", "yourself"
        # that were catching "tell about this pc" incorrectly.
        if any(w in ql for w in [
            "who are you","what are you",
            "tell me about yourself","introduce yourself",
            "your name","what can you do","what do you do",
            "your capabilities"
        ]):
            return (
                "I'm your **SOC AI Analyst** 🤖\n\n"
                "I monitor your infrastructure 24/7 using:\n"
                "• ML anomaly detection (Isolation Forest)\n"
                "• Signal correlation per device\n"
                "• Real-time CVE threat intelligence\n"
                "• RAG memory (FAISS vector store) — stores and retrieves "
                "past incidents for context\n"
                "• Phi-3 LLM for natural language analysis\n\n"
                f"Currently watching **{len(devs)} device(s)** with "
                f"**{len(fresh)} incidents** on record.\n\n"
                "Ask me anything — 'is my system safe?', "
                "'what happened on ayush?', 'tell about the rag system'"
            ), "rules"

        # ── 2. Greeting — only pure greetings, no "tell" ───
        # CHANGE: removed "tell" from greeting triggers.
        # "hi tell about yourself" was hitting this and getting
        # the generic greeting instead of going to Phi-3.
        if ql in ["hi","hello","hey","hiya","sup","howdy","greetings"] or \
           ql.startswith(("hi ","hello ","hey ","good morning","good evening")):
            if not fresh:
                return (
                    "Hey! I'm your SOC AI Analyst 🛡️\n\n"
                    "No incidents yet — start the agent to begin monitoring."
                ), "rules"
            high   = [i for i in fresh
                      if i["risk_level"] in ("CRITICAL","HIGH")]
            n      = len(high)
            status = "🚨 **ATTENTION REQUIRED**" if n > 0 else "✅ **ALL CLEAR**"
            msg    = (
                f"Hey! **{status}**\n\n"
                f"• {len(fresh)} incidents | {len(devs)} device(s): "
                f"{', '.join(devs)}\n"
                f"• {n} HIGH/CRITICAL\n"
                f"• Latest: {fresh[0]['risk_level']} on "
                f"{fresh[0]['device_name']}\n\n"
            )
            if n > 0:
                msg += (f"⚠️ Immediate attention: **"
                        f"{', '.join(set(i['device_name'] for i in high))}**")
            else:
                msg += "System looks normal."
            return msg, "rules"

        # ── 3. No data guard ─────────────────────────────────
        if not fresh:
            return (
                "No incidents yet.\n"
                "```bash\nSERVER_URL=http://localhost:8000 "
                "python3 agent/pc_agent.py\n```"
            ), "rules"

        high   = [i for i in fresh if i["risk_level"] in ("CRITICAL","HIGH")]
        latest = fresh[0]
        la     = latest.get("analysis",{})

        # ── 4. Pipeline / architecture ────────────────────────
        if any(w in ql for w in [
            "pipeline","how does it work","how it works",
            "architecture","explain the system",
            "how are you built","how do you work","system design"
        ]):
            return (
                "**SOC AI Pipeline:**\n\n"
                "```\n"
                "PC Agent (30s) → metrics\n"
                "  ↓\n"
                "ML APIs (Isolation Forest) → anomaly scores\n"
                "  ↓\n"
                "Correlation Engine → match by hostname\n"
                "  ↓\n"
                "RAG (FAISS + MiniLM) → top-3 similar incidents\n"
                "  ↓\n"
                "Threat Intel (DuckDuckGo) → CVE data\n"
                "  ↓\n"
                "Phi-3 LLM → risk + summary + actions\n"
                "  ↓\n"
                "SQLite → Streamlit Dashboard\n"
                "```\n\n"
                "**vs Microsoft Sentinel:**\n"
                "| | This | Sentinel |\n|---|---|---|\n"
                "| LLM | Phi-3 local | GPT-4 cloud |\n"
                "| Privacy | 100% local | Azure |\n"
                "| Cost | Free | $2,460+/mo |\n"
                "| Speed | ~1-2s | cloud |"
            ), "rules"

        # ── 5. Sentinel comparison ────────────────────────────
        if any(w in ql for w in [
            "sentinel","vs sentinel","versus sentinel",
            "compare to sentinel","vs microsoft","better than sentinel"
        ]):
            return (
                "**SOC AI vs Microsoft Sentinel:**\n\n"
                "| Feature | This | Sentinel |\n|---|---|---|\n"
                "| LLM | Phi-3 local | GPT-4 cloud |\n"
                "| Privacy | 100% on-device | Azure |\n"
                "| Cost | Free | $2,460+/mo |\n"
                "| ML | Custom IF | Built-in |\n"
                "| RAG | FAISS local | Azure Search |\n\n"
                "**Advantages:** privacy, zero cost, custom ML.\n"
                "**Sentinel:** enterprise scale, MS threat feeds."
            ), "rules"

        # ── 6. Explicit high/critical list ───────────────────
        if any(w in ql for w in [
            "show high","show critical","list alert","list high",
            "how many alert","how many critical","how many high",
            "all high","all critical"
        ]):
            if high:
                ha     = high[0].get("analysis",{})
                by_dev = {}
                for i in high:
                    by_dev[i["device_name"]] = \
                        by_dev.get(i["device_name"],0)+1
                return (
                    f"🚨 **{len(high)} HIGH/CRITICAL alerts**\n\n"
                    f"**Devices:** "
                    f"{', '.join(f'{d}({c})' for d,c in by_dev.items())}\n\n"
                    f"**Most recent:** "
                    f"{RISK_ICON.get(high[0]['risk_level'],'')} "
                    f"[{high[0]['risk_level']}] **{high[0]['device_name']}** "
                    f"@ {high[0]['timestamp'][:19]}\n\n"
                    f"**What:** {ha.get('summary','')}\n\n"
                    f"**Why:** {ha.get('root_cause','')}\n\n"
                    f"**Actions:**\n" +
                    "\n".join(f"• {x}"
                              for x in ha.get("recommended_actions",[]))
                ), "rules"
            return (
                f"✅ No HIGH/CRITICAL. All {len(fresh)} are MEDIUM/LOW."
            ), "rules"

        # ── 7. Latest incident ────────────────────────────────
        if any(w in ql for w in [
            "latest incident","last incident","most recent incident",
            "what just happened","newest incident"
        ]):
            return (
                f"{RISK_ICON.get(latest['risk_level'],'')} "
                f"**[{latest['risk_level']}] {latest['device_name']}**"
                f" @ {latest['timestamp'][:19]}\n\n"
                f"**What:** {la.get('summary','')}\n\n"
                f"**Why:** {la.get('root_cause','')}\n\n"
                f"**CPU:** {latest.get('ops_cpu',0):.0f}% | "
                f"**RAM:** {latest.get('ops_memory',0):.0f}%"
            ), "rules"

        # ── 8. Quick safety check — exact phrases only ────────
        # CHANGE: was catching "risk", "secure", "danger" broadly.
        # "is there risk in my cpu" was matching and giving the
        # short rule answer instead of going to Phi-3.
        # Now only exact "is my system safe" style phrases match.
        if any(w in ql for w in [
            "is my system safe","is my pc safe","is my cpu safe",
            "is everything safe","is everything fine","is everything ok",
            "am i safe","are we safe"
        ]):
            wr = worst_risk([i["risk_level"] for i in fresh])
            if wr in ("CRITICAL","HIGH") and high:
                h  = high[0]
                ha = h.get("analysis",{})
                return (
                    f"🚨 **System is at {wr} risk.**\n\n"
                    f"{len(high)} HIGH/CRITICAL alert(s) active.\n\n"
                    f"**Most urgent:** [{h['risk_level']}] "
                    f"{h['device_name']}\n"
                    f"{ha.get('summary','')}\n\n"
                    f"**Immediate action:**\n" +
                    "\n".join(f"• {x}"
                              for x in ha.get("recommended_actions",[])[:3])
                ), "rules"
            return (
                f"✅ **System is stable.** ({wr} overall risk)\n\n"
                f"{len(fresh)} incidents, none critical.\n"
                f"Devices: {', '.join(devs)}"
            ), "rules"

        # ── 9. Explicit remediation request ──────────────────
        if any(w in ql for w in [
            "what should i do","what to do next",
            "how to handle it","how do i fix this",
            "next steps","recommended actions","where to fix"
        ]):
            src = high[0] if high else latest
            sa  = src.get("analysis",{})
            return (
                f"**Handling [{src['risk_level']}] on "
                f"{src['device_name']}:**\n\n"
                f"**Situation:** {sa.get('summary','')}\n\n"
                f"**Root cause:** {sa.get('root_cause','')}\n\n"
                f"**Step-by-step:**\n" +
                "\n".join(f"{i+1}. {x}"
                          for i,x in
                          enumerate(sa.get("recommended_actions",[]))) +
                "\n\n**Where to apply:**\n" +
                "\n".join(f"📍 {l}" for l in sa.get("where_to_fix",[]))
            ), "rules"

        # ── 10. Status report ─────────────────────────────────
        if any(w in ql for w in [
            "status report","full report","give me a report",
            "give me status","full status","statistics"
        ]):
            by_risk = {}
            for i in fresh:
                by_risk[i["risk_level"]] = by_risk.get(i["risk_level"],0)+1
            lines = [
                f"**SOC Report** — {len(fresh)} incidents | "
                f"{len(devices)} devices | {len(high)} HIGH/CRITICAL\n",
                "**Risk breakdown:**"
            ]
            for r in ["CRITICAL","HIGH","MEDIUM","LOW"]:
                if r in by_risk:
                    lines.append(
                        f"{RISK_ICON.get(r,'')} {r}: {by_risk[r]} "
                        f"{'█'*min(by_risk[r],15)}"
                    )
            lines.append(
                f"\n⚠️ Action needed: "
                f"{', '.join(set(i['device_name'] for i in high))}"
                if high else "\n✅ No immediate action required"
            )
            return "\n".join(lines), "rules"

        # ── 11. Specific device ───────────────────────────────
        for dev in devs:
            if dev.lower() in ql:
                a, s = phi3()
                if a:
                    return a, s
                di     = [i for i in fresh if i["device_name"]==dev]
                wr     = worst_risk([i["risk_level"] for i in di])
                ld     = di[0] if di else {}
                da     = ld.get("analysis",{})
                n_high = sum(1 for i in di
                             if i["risk_level"] in ("CRITICAL","HIGH"))
                return (
                    f"**{dev}** — {len(di)} incidents | "
                    f"{RISK_ICON.get(wr,'')} {wr}\n\n"
                    f"CPU: {ld.get('ops_cpu',0):.0f}% | "
                    f"RAM: {ld.get('ops_memory',0):.0f}% | "
                    f"High/Critical: {n_high}\n\n"
                    f"**Latest:** {da.get('summary','N/A')}\n\n"
                    f"**Actions:**\n" +
                    "\n".join(f"• {x}"
                              for x in da.get("recommended_actions",[]))
                ), "rules"

        # ── 12. All devices ───────────────────────────────────
        if any(w in ql for w in [
            "list devices","what devices","which devices",
            "all devices","monitored devices","show devices"
        ]):
            lines = [f"**{len(devs)} device(s):**\n"]
            for d in devs:
                di = [i for i in fresh if i["device_name"]==d]
                wr = worst_risk([i["risk_level"] for i in di])
                ld = di[0] if di else {}
                lines.append(
                    f"• **{d}**: {len(di)} incidents | "
                    f"{RISK_ICON.get(wr,'')} {wr} | "
                    f"CPU {ld.get('ops_cpu',0):.0f}% | "
                    f"RAM {ld.get('ops_memory',0):.0f}%"
                )
            return "\n".join(lines), "rules"

        # ── 13. EVERYTHING ELSE → PHI-3 ──────────────────────
        # This now correctly catches:
        # "tell about this pc and my rag system"
        # "is there risk in my cpu"
        # "tell about yourself" (after hi)
        # "is my pc working fine or there is any error"
        # "tell about any other incident similar to it"
        # "tell about the llm"
        # "why is cpu high", "explain the anomaly", etc.
        a, s = phi3()
        if a:
            return a, s

        # Phi-3 offline / empty response fallback
        wr_overall = worst_risk([i["risk_level"] for i in fresh])
        return (
            f"**{RISK_ICON.get(wr_overall,'')} {wr_overall} risk** | "
            f"{len(fresh)} incidents | {len(devs)} device(s)\n\n"
            "💡 Try asking:\n"
            "• *'is my system safe?'*\n"
            "• *'show high risk alerts'*\n"
            "• *'give me a status report'*\n"
            "• *'what actions should I take?'*\n"
            "• *'what happened on ayush?'*"
        ), "rules"

    # ── Chat render ────────────────────────────────────────
    for msg in st.session_state.chat:
        css  = "chat-user" if msg["role"]=="user" else "chat-bot"
        icon = "👤" if msg["role"]=="user" else "🤖"
        src  = msg.get("source","")
        tag  = (
            '<span class="phi3-tag">⚡ Phi-3 LLM</span>'
            if src=="phi3" else
            '<span class="phi3-tag">📋 Rule-based</span>'
            if src=="rules" else ""
        )
        st.markdown(
            f'<div class="{css}">{icon}&nbsp;{msg["content"]}{tag}</div>',
            unsafe_allow_html=True
        )

    st.divider()
    st.markdown("**Quick queries:**")
    cols = st.columns(5)
    for col, (label, prompt) in zip(cols, [
        ("📊 Status",   "Give me a status report"),
        ("🚨 High risk","Show all high risk alerts"),
        ("🕐 Latest",   "What is the latest incident?"),
        ("🔧 Handle",   "What should I do next?"),
        ("⚙️ Pipeline", "How does the pipeline work?"),
    ]):
        if col.button(label, use_container_width=True):
            st.session_state.chat.append(
                {"role":"user","content":prompt}
            )
            with st.spinner("Analyzing..."):
                ans, src = answer(prompt)
            st.session_state.chat.append(
                {"role":"assistant","content":ans,"source":src}
            )
            st.rerun()

    if st.button("🗑️ Clear chat"):
        st.session_state.chat = []
        st.rerun()

    user_input = st.chat_input(
        "Ask anything — 'is my cpu safe?', 'tell about the rag system', "
        "'what happened on ayush?'"
    )
    if user_input and user_input.strip():
        st.session_state.chat.append(
            {"role":"user","content":user_input}
        )
        with st.spinner("Analyzing..."):
            ans, src = answer(user_input)
        st.session_state.chat.append(
            {"role":"assistant","content":ans,"source":src}
        )
        st.rerun()


# ══════════════════════════════════════════════════════════
# PAGE 3 — DEVICE CONTROLS
# ══════════════════════════════════════════════════════════
elif page == "🔧 Device Controls":
    st.title("🔧 Device Controls")

    if not incidents:
        st.info("No incidents yet — start the PC agent first.")
        st.stop()

    selected   = st.selectbox("Select device", devices)
    dev_inc    = [i for i in incidents if i["device_name"]==selected]
    latest_dev = dev_inc[0] if dev_inc else {}

    try:
        status = requests.get(
            f"{API}/agent/status/{selected}", timeout=3
        ).json().get("status","active")
    except:
        status = "unknown"

    wr = worst_risk([i["risk_level"] for i in dev_inc]) if dev_inc else "NONE"

    sc1,sc2,sc3,sc4 = st.columns(4)
    sc1.metric("Agent status", status.upper())
    sc2.metric("Incidents",    len(dev_inc))
    sc3.metric("Worst risk",   f"{RISK_ICON.get(wr,'')} {wr}")
    sc4.metric("Latest CPU",
               f"{latest_dev.get('ops_cpu',0):.1f}%"
               if dev_inc else "N/A")
    st.divider()

    st.subheader("Agent control")
    cc1,cc2,cc3 = st.columns(3)
    if cc1.button("⏸️ Pause", use_container_width=True):
        try:
            requests.post(f"{API}/agent/control",
                          json={"device_name":selected,"action":"pause"},
                          timeout=3)
            st.success(f"Paused {selected}")
            st.cache_data.clear()
        except:
            st.error("Failed")

    if cc2.button("▶️ Resume", use_container_width=True):
        try:
            requests.post(f"{API}/agent/control",
                          json={"device_name":selected,"action":"start"},
                          timeout=3)
            st.success(f"Resumed {selected}")
            st.cache_data.clear()
        except:
            st.error("Failed")

    if cc3.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.subheader("Manual alert")
    reason = st.text_area("Reason",
                          placeholder="Describe the security concern...")
    sev = st.selectbox("Severity", ["HIGH","CRITICAL","MEDIUM","LOW"])
    if st.button("🚨 Trigger alert", type="primary"):
        if reason.strip():
            try:
                requests.post(f"{API}/alert",
                              json={"device_name":selected,
                                    "reason":reason,"severity":sev},
                              timeout=3)
                st.success(f"Alert triggered for {selected}")
                st.cache_data.clear()
            except:
                st.error("Failed")
        else:
            st.warning("Enter a reason first.")

    st.divider()
    st.subheader(f"Incident history — {selected}")
    for row in dev_inc[:15]:
        a    = row.get("analysis",{})
        risk = row.get("risk_level","UNKNOWN")
        with st.expander(
            f"{RISK_ICON.get(risk,'⚪')} [{risk}] {row['timestamp'][:19]}"
        ):
            c1,c2 = st.columns(2)
            with c1:
                st.write(f"**Summary:** {a.get('summary','N/A')}")
                st.write(f"**Root cause:** {a.get('root_cause','N/A')}")
            with c2:
                st.progress(min(int(row.get("ops_cpu",0)),100),
                            text=f"CPU {row.get('ops_cpu',0):.0f}%")
                st.progress(min(int(row.get("ops_memory",0)),100),
                            text=f"RAM {row.get('ops_memory',0):.0f}%")
                for act in a.get("recommended_actions",[]):
                    st.write(f"→ {act}")