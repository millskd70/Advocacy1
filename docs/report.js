/* Bill report builder: turns a set of tracked bills into
 *   - a Word document (.docx), built in the browser with no outside services, and
 *   - a print-ready page (Print / Save as PDF).
 * Depends on XlsxWriter.zip (xlsx-writer.js) for packaging the .docx.
 */
(function (global) {
  "use strict";
  const enc = new TextEncoder();
  const x = s => String(s ?? "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const fmtDate = d => {
    if (!d) return "";
    const t = new Date(String(d).slice(0, 10) + "T12:00:00");
    return isNaN(t) ? d : t.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };
  const sessionLabel = b => { const m = /^b(\d{4})_(\d{2})$/.exec(b || ""); return m ? `${m[1]}–20${m[2]} Legislative Session` : (b || ""); };

  // ------------------------------------------------------------------ model
  function model(bills, hearings, meta, opts) {
    const hearingsFor = no => hearings.filter(h => (h.bills || []).includes(no))
      .sort((a, b) => ((a.date || "") + (a.time || "")).localeCompare((b.date || "") + (b.time || "")));
    return {
      title: opts.title || "Kansas Legislation Report",
      runDate: new Date().toLocaleString("en-US", { dateStyle: "long", timeStyle: "short" }),
      dataDate: meta.generated_at ? new Date(meta.generated_at).toLocaleString("en-US", { dateStyle: "long", timeStyle: "short" }) : "",
      session: sessionLabel(meta.biennium),
      opts,
      bills: bills.map(b => ({ ...b, _hearings: hearingsFor(b.bill_no) })),
    };
  }
  const voteText = v => {
    const a = (v.action || "").trim(), mo = (v.motion || "").trim();
    const dup = !mo || a.toLowerCase().includes(mo.toLowerCase()) || mo.toLowerCase().includes(a.toLowerCase());
    return (a && mo && !dup ? `${a} (${mo})` : (a || mo)) || "Roll call";
  };
  const otherVotes = v => (v.present || 0) + (v.absent || 0) + (v.not_voting || 0);
  const facts = b => [
    ["Status", b.stage || ""],
    ["Last action", [b.last_action, b.last_action_date ? `(${fmtDate(b.last_action_date)})` : ""].filter(Boolean).join(" ")],
    ["Type", `${b.type || ""} · ${b.chamber || ""}`],
    ["Introduced", fmtDate(b.intro_date)],
    ["Original sponsor", (b.original_sponsor || []).join("; ") || "—"],
    ["Sponsors", (b.sponsors || []).join("; ") || "—"],
    ["Committees", (b.committees || []).join("; ") || "—"],
    ["Topics", (b.topics || []).join(", ")],
  ];
  const hearingLine = h => `${fmtDate(h.date)}${h.time ? `, ${h.time}` : ""} — ${h.committee || "Committee"}` +
    `${h.room ? `, Room ${h.room}` : ""}${h.status ? ` (${h.status})` : ""}`;

  // ------------------------------------------------------------------ HTML (print / PDF)
  function html(m) {
    const css = `
      body{font:11pt/1.4 Calibri,"Segoe UI",Arial,sans-serif;color:#1c2430;margin:0;background:#fff}
      .wrap{max-width:8in;margin:0 auto;padding:.4in .5in}
      .bar{position:sticky;top:0;background:#1f3a5f;color:#fff;padding:10px 16px;display:flex;gap:10px;align-items:center;justify-content:space-between;font:14px -apple-system,Segoe UI,sans-serif}
      .bar button{font:inherit;font-weight:600;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;background:#c8962e;color:#1c1300}
      h1{font-size:20pt;color:#1f3a5f;margin:0 0 4px} .meta{color:#5b6573;font-size:10pt;margin-bottom:14px}
      h2{font-size:13.5pt;color:#1f3a5f;border-bottom:2px solid #c8962e;padding-bottom:3px;margin:22px 0 8px;break-after:avoid}
      h3{font-size:11pt;color:#1f3a5f;margin:12px 0 4px;break-after:avoid}
      table{width:100%;border-collapse:collapse;font-size:9.5pt;margin:4px 0 8px;page-break-inside:auto}
      th,td{border:1px solid #c9d1db;padding:4px 6px;text-align:left;vertical-align:top} tr{break-inside:avoid}
      th{background:#1f3a5f;color:#fff;font-weight:600} td.n{text-align:right;white-space:nowrap}
      table.facts th{background:#eef2f7;color:#1c2430;width:24%}
      .muted{color:#5b6573} a{color:#1f5fa8}
      .bill{break-before:auto} ul{margin:4px 0 8px 18px;padding:0;font-size:10pt}
      @media print{.bar{display:none}.wrap{padding:0;max-width:none}@page{margin:.6in}}
    `;
    const table = (head, rows, cls) => `<table${cls ? ` class="${cls}"` : ""}><thead><tr>${head.map(h => `<th>${x(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
    let out = `<div class="bar"><span>${x(m.title)}</span><button onclick="window.print()">Print / Save as PDF</button></div><div class="wrap">`;
    out += `<h1>${x(m.title)}</h1><div class="meta">Report run date: <b>${x(m.runDate)}</b><br>`;
    out += `Data current as of: ${x(m.dataDate)} · ${x(m.session)} · ${m.bills.length} measure${m.bills.length === 1 ? "" : "s"}</div>`;
    out += `<h2>Summary</h2>` + table(["Measure", "Title", "Status", "Last action"], m.bills.map(b =>
      `<tr><td><b>${x(b.name)}</b></td><td>${x(b.short_title || b.long_title)}</td><td>${x(b.stage)}</td><td>${x(b.last_action)}<br><span class="muted">${x(fmtDate(b.last_action_date))}</span></td></tr>`));
    for (const b of m.bills) {
      out += `<div class="bill"><h2>${x(b.name)} — ${x(b.short_title || b.long_title)}</h2>`;
      out += `<table class="facts"><tbody>${facts(b).map(([k, v]) => `<tr><th>${x(k)}</th><td>${x(v)}</td></tr>`).join("")}
        <tr><th>Official page</th><td><a href="${x(b.url)}">${x(b.url)}</a></td></tr></tbody></table>`;
      if (b.long_title && b.long_title !== b.short_title) out += `<h3>Full title</h3><div>${x(b.long_title)}</div>`;
      if (m.opts.votes) {
        out += `<h3>Votes</h3>`;
        out += (b.votes || []).length ? table(["Date", "Chamber", "Action", "Yea", "Nay", "Other*"], b.votes.map(v =>
          `<tr><td>${x(fmtDate(v.date))}</td><td>${x(v.chamber)}</td><td>${x(voteText(v))}</td><td class="n">${v.yea}</td><td class="n">${v.nay}</td><td class="n">${otherVotes(v)}</td></tr>`))
          : `<div class="muted">No recorded roll-call votes.</div>`;
      }
      if (m.opts.hearings) {
        out += `<h3>Hearings</h3>` + ((b._hearings || []).length ? `<ul>${b._hearings.map(h => `<li>${x(hearingLine(h))}</li>`).join("")}</ul>` : `<div class="muted">No hearings recorded.</div>`);
      }
      if (m.opts.history) {
        out += `<h3>Action history</h3>` + ((b.history || []).length ? table(["Date", "Chamber", "Action"], b.history.map(h =>
          `<tr><td style="white-space:nowrap">${x(fmtDate(h.date))}</td><td>${x(h.chamber)}</td><td>${x(h.action)}</td></tr>`)) : `<div class="muted">No actions recorded.</div>`);
      }
      out += `</div>`;
    }
    out += `<p class="muted" style="margin-top:22px;font-size:9pt">*Other = present and passing, absent, or not voting. Source: Kansas Legislature (kslegislature.gov). Status is derived from the official action history; confirm details on each bill's official page.</p></div>`;
    return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${x(m.title)}</title><style>${css}</style></head><body>${out}</body></html>`;
  }

  // ------------------------------------------------------------------ DOCX
  const W = 10080; // text width in twips (8.5in - 2 x 0.75in)
  const run = (text, o = {}) => {
    const rPr = [o.bold ? "<w:b/>" : "", o.color ? `<w:color w:val="${o.color}"/>` : "", o.size ? `<w:sz w:val="${o.size}"/>` : "",
                 o.style ? `<w:rStyle w:val="${o.style}"/>` : ""].join("");
    const parts = String(text ?? "").split("\n");
    return parts.map((t, i) => `<w:r>${rPr ? `<w:rPr>${rPr}</w:rPr>` : ""}${i ? "<w:br/>" : ""}<w:t xml:space="preserve">${x(t)}</w:t></w:r>`).join("");
  };
  const para = (content, o = {}) => {
    const pPr = [o.style ? `<w:pStyle w:val="${o.style}"/>` : "", o.keepNext ? "<w:keepNext/>" : "",
                 o.after !== undefined ? `<w:spacing w:after="${o.after}"/>` : "", o.align ? `<w:jc w:val="${o.align}"/>` : ""].join("");
    return `<w:p>${pPr ? `<w:pPr>${pPr}</w:pPr>` : ""}${content}</w:p>`;
  };
  function docxTable(widths, head, rows, o = {}) {
    const tw = widths.map(f => Math.round(f * W));
    const border = `<w:top w:val="single" w:sz="4" w:color="C9D1DB"/><w:left w:val="single" w:sz="4" w:color="C9D1DB"/><w:bottom w:val="single" w:sz="4" w:color="C9D1DB"/><w:right w:val="single" w:sz="4" w:color="C9D1DB"/><w:insideH w:val="single" w:sz="4" w:color="C9D1DB"/><w:insideV w:val="single" w:sz="4" w:color="C9D1DB"/>`;
    const cell = (content, i, shade, isHead, right) =>
      `<w:tc><w:tcPr><w:tcW w:w="${tw[i]}" w:type="dxa"/>${shade ? `<w:shd w:val="clear" w:color="auto" w:fill="${shade}"/>` : ""}</w:tcPr>` +
      `<w:p><w:pPr><w:pStyle w:val="TableText"/>${right ? '<w:jc w:val="right"/>' : ""}</w:pPr>${typeof content === "object" && content && content.raw ? content.raw : run(content, isHead ? { bold: true, color: o.facts ? "1C2430" : "FFFFFF" } : {})}</w:p></w:tc>`;
    let xml = `<w:tbl><w:tblPr><w:tblW w:w="${W}" w:type="dxa"/><w:tblBorders>${border}</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>`;
    xml += `<w:tblGrid>${tw.map(w => `<w:gridCol w:w="${w}"/>`).join("")}</w:tblGrid>`;
    if (head) xml += `<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>${head.map((h, i) => cell(h, i, "1F3A5F", true)).join("")}</w:tr>`;
    for (const r of rows) {
      xml += `<w:tr><w:trPr><w:cantSplit/></w:trPr>${r.map((c, i) => o.facts && i === 0 ? cell(c, i, "EEF2F7", true) : cell(c, i, null, false, (o.right || []).includes(i))).join("")}</w:tr>`;
    }
    return xml + `</w:tbl>` + para("", { after: 60 });
  }

  function docx(m) {
    const links = [];
    const link = (url, text) => { links.push(url); return { raw: `<w:hyperlink r:id="rIdL${links.length}" w:history="1">${run(text, { style: "Hyperlink" })}</w:hyperlink>` }; };
    let body = "";
    body += para(run(m.title), { style: "Title" });
    body += para(run("Report run date: ", { bold: true }) + run(m.runDate), { after: 0 });
    body += para(run(`Data current as of: ${m.dataDate} · ${m.session} · ${m.bills.length} measure${m.bills.length === 1 ? "" : "s"}`, { color: "5B6573" }), { after: 200 });
    body += para(run("Summary"), { style: "Heading1" });
    body += docxTable([0.13, 0.42, 0.17, 0.28], ["Measure", "Title", "Status", "Last action"],
      m.bills.map(b => [b.name, b.short_title || b.long_title, b.stage, `${b.last_action}${b.last_action_date ? `\n${fmtDate(b.last_action_date)}` : ""}`]));
    for (const b of m.bills) {
      body += para(run(`${b.name} — ${b.short_title || b.long_title}`), { style: "Heading1" });
      const rows = facts(b).map(([k, v]) => [k, v]);
      rows.push(["Official page", link(b.url, b.url)]);
      body += docxTable([0.24, 0.76], null, rows, { facts: true });
      if (b.long_title && b.long_title !== b.short_title) {
        body += para(run("Full title"), { style: "Heading2" }) + para(run(b.long_title));
      }
      if (m.opts.votes) {
        body += para(run("Votes"), { style: "Heading2" });
        body += (b.votes || []).length
          ? docxTable([0.15, 0.12, 0.43, 0.1, 0.1, 0.1], ["Date", "Chamber", "Action", "Yea", "Nay", "Other*"],
              b.votes.map(v => [fmtDate(v.date), v.chamber, voteText(v), String(v.yea), String(v.nay), String(otherVotes(v))]), { right: [3, 4, 5] })
          : para(run("No recorded roll-call votes.", { color: "5B6573" }));
      }
      if (m.opts.hearings) {
        body += para(run("Hearings"), { style: "Heading2" });
        body += (b._hearings || []).length ? b._hearings.map(h => para(run(hearingLine(h)), { style: "ListBullet" })).join("")
          : para(run("No hearings recorded.", { color: "5B6573" }));
      }
      if (m.opts.history) {
        body += para(run("Action history"), { style: "Heading2" });
        body += (b.history || []).length
          ? docxTable([0.15, 0.12, 0.73], ["Date", "Chamber", "Action"], b.history.map(h => [fmtDate(h.date), h.chamber, h.action]))
          : para(run("No actions recorded.", { color: "5B6573" }));
      }
    }
    body += para(run("*Other = present and passing, absent, or not voting. Source: Kansas Legislature (kslegislature.gov). Status is derived from the official action history; confirm details on each bill's official page.", { color: "5B6573", size: 17 }));

    const sect = `<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="540" w:footer="540" w:gutter="0"/></w:sectPr>`;
    const NS = `xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"`;
    const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${NS}><w:body>${body}${sect}</w:body></w:document>`;
    const footerXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr ${NS}><w:p><w:pPr><w:pStyle w:val="Footer"/><w:tabs><w:tab w:val="right" w:pos="${W}"/></w:tabs></w:pPr>${run(`${m.title} · Run ${m.runDate}`)}<w:r><w:tab/><w:t xml:space="preserve">Page </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>`;
    const stylesXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3A5F"/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="2" w:color="C8962E"/></w:pBdr><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3A5F"/><w:sz w:val="27"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3A5F"/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:spacing w:after="40"/><w:ind w:left="360" w:hanging="240"/></w:pPr><w:rPr><w:sz w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="5B6573"/><w:sz w:val="16"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="1F5FA8"/><w:u w:val="single"/></w:rPr></w:style>
</w:styles>`;
    const numberingXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="240"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>`;
    const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
${links.map((u, i) => `<Relationship Id="rIdL${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="${x(u)}" TargetMode="External"/>`).join("\n")}
</Relationships>`;
    const files = [
      { name: "[Content_Types].xml", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>` },
      { name: "_rels/.rels", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>` },
      { name: "docProps/core.xml", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>${x(m.title)}</dc:title><dc:creator>Kansas Legislation Tracker</dc:creator>
<dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString().replace(/\.\d+Z$/, "Z")}</dcterms:created></cp:coreProperties>` },
      { name: "word/document.xml", data: documentXml },
      { name: "word/styles.xml", data: stylesXml },
      { name: "word/numbering.xml", data: numberingXml },
      { name: "word/footer1.xml", data: footerXml },
      { name: "word/_rels/document.xml.rels", data: rels },
    ].map(f => ({ name: f.name, data: enc.encode(f.data) }));
    const blob = global.XlsxWriter.zip(files);
    return new Blob([blob], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
  }

  global.ReportBuilder = { model, html, docx };
})(window);
