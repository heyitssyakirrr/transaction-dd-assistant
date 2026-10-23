"""The report as one self-contained HTML page, in the order an analyst works:

  verdict -> account at a glance -> account story -> what to verify first -> questions for the customer
  -> findings (each with exact figures and its transactions) -> pattern checklist -> monthly timeline
  -> considered and rejected -> limitations and issues -> what the AI checked -> processing

Each section is labelled "AI" (written by the AI) or "exact" (computed by code). All text is escaped and
nothing is loaded from outside the page.
"""
from __future__ import annotations

from decimal import Decimal
from html import escape

from app.report.model import Figures, FindingCard, Report, TxnRow

_RISK_COLOURS = {"high": "#b42318", "medium": "#b54708", "low": "#067647", "not_assessed": "#475467"}
_STATUS = {"found": "Found", "not_found": "Not found", "cannot_check": "Cannot check", "not_reported": "Not reported"}


def render(report: Report) -> str:
    sections = [
        _header(report), _verdict(report), _glance(report),
        _block("Account story", "AI", f"<p>{e(report.account_story) or _muted('Not available.')}</p>"),
        _verify_first(report), _questions(report), _findings(report), _checklist(report), _months(report),
        _rejected(report), _limitations(report), _tools(report), _processing(report),
    ]
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'><title>Transaction review {e(report.file_name)}</title>
<style>{_CSS}</style></head><body><main>{''.join(sections)}</main></body></html>"""


# --- the top of the page ------------------------------------------------------------------------

def _header(report: Report) -> str:
    return (f"<header><h1>Transaction review</h1><p class='muted'>{e(report.file_name)} &middot; "
            f"{e(report.period_start)} to {e(report.period_end)} &middot; {report.transactions:,} transactions</p>"
            "</header>")


def _verdict(report: Report) -> str:
    colour = _RISK_COLOURS.get(report.risk_level, "#475467")
    warning = ("<p class='warn'>Part of this review was not done (see Limitations). Do not rely on this report "
               "alone.</p>" if report.status == "incomplete" else "")
    return f"""<section class='verdict' style='border-color:{colour}'>
<div><span class='risk' style='background:{colour}'>{e(report.risk_level.replace('_', ' ').upper())} RISK</span>
<span class='muted'>&nbsp;Evidence: {e(report.evidence_strength)}</span> <span class='source'>AI</span></div>
<h2 class='headline'>{e(report.headline)}</h2>
<p><b>Why this risk level:</b> {e(report.risk_reason)}</p>{warning}
<p class='muted small'>AI assessment to support the analyst. The analyst decides what action to take.</p></section>"""


def _glance(report: Report) -> str:
    g = report.glance
    tiles = [
        ("Money in", f"RM {money(g.total_in)}", f"{g.count_in:,} credits"),
        ("Money out", f"RM {money(g.total_out)}", f"{g.count_out:,} debits"),
        ("In minus out", f"RM {money(g.in_minus_out)}", "over the period"),
        ("Activity", f"{g.transactions:,} transactions", f"on {g.active_days} of {g.days_in_period} days"),
        ("Largest credit", f"RM {money(g.largest_in.amount)}" if g.largest_in else "none",
         f"{g.largest_in.tid} on {g.largest_in.date}" if g.largest_in else ""),
        ("Largest debit", f"RM {money(g.largest_out.amount)}" if g.largest_out else "none",
         f"{g.largest_out.tid} on {g.largest_out.date}" if g.largest_out else ""),
        ("Longest quiet period", g.longest_quiet or "none", "no transactions in between"),
        ("Last credit", g.last_credit or "none", "the last money in"),
    ]
    body = "".join(f"<div class='tile'><div class='label'>{e(label)}</div><div class='value'>{e(value)}</div>"
                   f"<div class='muted small'>{e(note)}</div></div>" for label, value, note in tiles)
    empty = (f"<p class='muted small'>Months with no transactions: {e(', '.join(g.months_without_activity))}</p>"
             if g.months_without_activity else "")
    return _block("Account at a glance", "exact", f"<div class='tiles'>{body}</div>{empty}")


def _verify_first(report: Report) -> str:
    if not report.verify_first:
        return _block("What to verify first", "AI", _muted("No checks were suggested."))
    items = "".join(f"<li><p>{e(item.action)}</p>{_issues(item.issues)}{_table(item.transactions, 8)}</li>"
                    for item in report.verify_first)
    return _block("What to verify first", "AI", f"<ol class='steps'>{items}</ol>")


def _questions(report: Report) -> str:
    if not report.customer_questions:
        return ""
    items = "".join(f"<li>{e(q)}</li>" for q in report.customer_questions)
    return _block("Questions for the customer or relationship manager", "AI", f"<ol>{items}</ol>")


# --- findings -------------------------------------------------------------------------------------

def _findings(report: Report) -> str:
    if not report.findings:
        return _block("Findings", "AI + exact", _muted("No pattern was confirmed against the transactions."))
    return _block("Findings", "AI + exact", "".join(_card(f) for f in report.findings))


def _card(f: FindingCard) -> str:
    parts = [("Why it matters", f.why_it_matters), ("Ordinary explanation to rule out", f.ordinary_explanation),
             ("What to verify", f.what_to_verify)]
    details = "".join(f"<dt>{label}</dt><dd>{e(text)}</dd>" for label, text in parts if text)
    return f"""<article class='finding'>
<h3>{e(f.finding_id)} &middot; {e(f.title)} <span class='tag {e(f.strength)}'>{e(f.strength)}</span></h3>
{_figures(f.figures)}<p>{e(f.what_happened)}</p><dl>{details}</dl>{_issues(f.issues)}{_table(f.transactions, 15)}
</article>"""


def _figures(fig: Figures) -> str:
    parts = [f"{fig.count} transaction(s)", f"in RM {money(fig.total_in)} ({fig.count_in})",
             f"out RM {money(fig.total_out)} ({fig.count_out})"]
    if fig.out_share_of_in is not None:
        parts.append(f"out = {fig.out_share_of_in}% of in")
    if fig.first_date:
        parts.append(f"{fig.first_date} to {fig.last_date} ({fig.days} day{'' if fig.days == 1 else 's'})")
    return f"<p class='figures'>{' &middot; '.join(e(p) for p in parts)}</p>"


def _table(rows: list[TxnRow], open_up_to: int) -> str:
    """The transactions, folded when there are many."""
    if not rows:
        return ""
    total_in = sum((r.amount for r in rows if r.direction == "C"), Decimal("0"))
    total_out = sum((r.amount for r in rows if r.direction == "D"), Decimal("0"))
    body = "".join(f"<tr><td>{e(r.tid)}</td><td>{e(r.date)}</td><td class='num'>{r.seq}</td>"
                   f"<td>{'In' if r.direction == 'C' else 'Out'}</td><td class='num'>{money(r.amount)}</td></tr>"
                   for r in rows)
    summary = f"{len(rows)} transaction(s): in RM {money(total_in)}, out RM {money(total_out)}"
    return (f"<details{' open' if len(rows) <= open_up_to else ''}><summary>{summary}</summary><div class='scroll'>"
            "<table><thead><tr><th>ID</th><th>Date</th><th class='num'>Seq</th><th>In/Out</th>"
            f"<th class='num'>Amount (RM)</th></tr></thead><tbody>{body}</tbody></table></div></details>")


# --- the rest ---------------------------------------------------------------------------------------

def _checklist(report: Report) -> str:
    body = "".join(f"<tr><td>{e(r.title)}</td><td><span class='status {r.status}'>{_STATUS[r.status]}</span></td>"
                   f"<td>{e(r.note)}</td></tr>" for r in report.checklist)
    return _block("Pattern checklist", "AI + exact", "<div class='scroll'><table><thead><tr><th>Pattern</th>"
                  f"<th>Result</th><th>Note</th></tr></thead><tbody>{body}</tbody></table></div>")


def _months(report: Report) -> str:
    body = "".join(
        f"<tr{' class=quiet' if m.count == 0 else ''}><td>{e(m.month)}</td><td class='num'>{m.count:,}</td>"
        f"<td class='num'>{money(m.total_in)} ({m.count_in})</td><td class='num'>{money(m.total_out)} ({m.count_out})</td>"
        f"<td>{e(m.note)}</td></tr>" for m in report.months)
    return _block("Monthly timeline", "exact figures, AI notes", "<div class='scroll'><table><thead><tr>"
                  "<th>Month</th><th class='num'>Count</th><th class='num'>In, RM (count)</th>"
                  "<th class='num'>Out, RM (count)</th><th>Note</th></tr></thead>"
                  f"<tbody>{body}</tbody></table></div>")


def _rejected(report: Report) -> str:
    if not report.rejected:
        return ""
    items = "".join(f"<li><b>{e(r.title)}:</b> {e(r.reason)}</li>" for r in report.rejected)
    return _block("Considered and rejected", "AI",
                  f"<p class='muted small'>Suspected patterns the AI checked and ruled out.</p><ul>{items}</ul>")


def _limitations(report: Report) -> str:
    html = _block("Limitations", "", "<ul>" + "".join(f"<li>{e(item)}</li>" for item in report.limitations) + "</ul>")
    if report.issues:
        html += _block("Issues found by the checks", "", _issues(report.issues))
    return html


def _tools(report: Report) -> str:
    if not report.tool_uses:
        return ""
    body = "".join(f"<tr><td>{e(t.step)}</td><td>{e(t.tool)}</td><td><code>{e(t.asked)}</code></td>"
                   f"<td>{e(t.answer)}</td></tr>" for t in report.tool_uses)
    return _block("What the AI checked", "exact", f"<details><summary>{len(report.tool_uses)} tool use(s)</summary>"
                  "<div class='scroll'><table><thead><tr><th>Step</th><th>Tool</th><th>Asked</th>"
                  f"<th>Answer (first line)</th></tr></thead><tbody>{body}</tbody></table></div></details>")


def _processing(report: Report) -> str:
    body = "".join(f"<tr><td>{e(c.step)}</td><td>{'Answered' if c.status == 'answered' else 'Failed'}</td>"
                   f"<td class='num'>{c.seconds}</td><td class='num'>{c.requests}</td><td class='num'>{c.tool_uses}</td>"
                   f"<td class='num'>{c.output_tokens:,}</td><td>{e(c.problem)}</td></tr>" for c in report.calls)
    return _block("Processing", "", f"<p class='muted'>{report.total_seconds} s, {len(report.calls)} AI calls, "
                  f"{report.groups} group(s).</p><details><summary>Each call</summary><div class='scroll'><table>"
                  "<thead><tr><th>Step</th><th>Status</th><th class='num'>Seconds</th><th class='num'>Requests</th>"
                  "<th class='num'>Tool uses</th><th class='num'>Output tokens</th><th>Problem</th></tr></thead>"
                  f"<tbody>{body}</tbody></table></div></details>")


# --- helpers ----------------------------------------------------------------------------------------

def _issues(issues: list[str]) -> str:
    if not issues:
        return ""
    return "<div class='issues'><b>Check:</b><ul>" + "".join(f"<li>{e(i)}</li>" for i in issues) + "</ul></div>"


def _block(title: str, source: str, body: str) -> str:
    label = f" <span class='source'>{e(source)}</span>" if source else ""
    return f"<section><h2>{e(title)}{label}</h2>{body}</section>"


def _muted(text: str) -> str:
    return f"<span class='muted'>{e(text)}</span>"


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def e(text: object) -> str:
    return escape(str(text or ""), quote=True)


_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2433;--muted:#5b6475;--line:#e3e6eb;--head:#f2f4f7}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:0 0 10px}h3{font-size:15px;margin:0 0 6px}
section,header{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px 18px;margin:0 0 14px}
.muted{color:var(--muted)}.small{font-size:12px}
.source{font-size:11px;font-weight:500;color:var(--muted);border:1px solid var(--line);border-radius:10px;padding:0 7px;
margin-left:6px;vertical-align:middle}
.verdict{border-left:6px solid}.risk{display:inline-block;color:#fff;font-weight:700;padding:4px 10px;border-radius:6px}
.headline{font-size:17px;margin:12px 0 8px}
.warn{background:#fff4e5;border:1px solid #f5c26b;padding:8px 10px;border-radius:6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:6px;padding:8px 10px}.tile .label{font-size:12px;color:var(--muted)}
.tile .value{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}
.finding{border-top:1px solid var(--line);padding:14px 0}.finding:first-of-type{border-top:0;padding-top:0}
.figures{background:var(--head);border-radius:6px;padding:6px 10px;font-variant-numeric:tabular-nums}
.tag{font-size:12px;font-weight:500;background:#eef1f5;border-radius:10px;padding:1px 8px;margin-left:6px}
.tag.strong{background:#fde2df;color:#912018}.tag.moderate{background:#fff4e5;color:#93370d}
dl{margin:8px 0}dt{font-weight:600;margin-top:6px}dd{margin:0}
.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #eceef2;vertical-align:top}th{background:var(--head)}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}tr.quiet td{color:var(--muted)}
details summary{cursor:pointer;color:#344054;margin:6px 0}code{font-size:12px}
.issues{background:#fdecea;border-left:3px solid #b42318;padding:6px 10px;margin:8px 0;border-radius:4px}
.issues ul{margin:4px 0 0;padding-left:18px}
.status{border-radius:10px;padding:1px 8px;font-size:12px;white-space:nowrap}.status.found{background:#fde2df;color:#912018}
.status.not_found{background:#e6f4ea;color:#05603a}.status.cannot_check{background:#eef1f5;color:#475467}
.status.not_reported{background:#fff4e5;color:#93370d}ol.steps li{margin-bottom:8px}
"""
