/* Minimal, dependency-free Excel (.xlsx) writer for the tracker page.
 *
 *   const blob = XlsxWriter.build([
 *     { name: "Bills",
 *       columns: [{ header: "Bill", width: 10, type: "link" }, { header: "Date", type: "date" }, ...],
 *       rows: [[{ text: "SB 1", url: "https://..." }, "2026-02-01", ...]] },
 *   ]);
 *
 * Column types: "text" (default), "wrap" (wrapped text), "date" (YYYY-MM-DD -> real Excel date),
 * "number", "link" (cell value {text, url} -> clickable hyperlink).
 * Each sheet gets a bold, frozen header row with filter buttons, like Excel's AutoFilter.
 */
(function (global) {
  "use strict";
  const enc = new TextEncoder();
  const xmlEsc = s => String(s ?? "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  // ------------------------------------------------------------ ZIP (stored, no compression)
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function zip(files) {  // files: [{name, data: Uint8Array}]
    const parts = [], central = [];
    let offset = 0;
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    for (const f of files) {
      const name = enc.encode(f.name), data = f.data, crc = crc32(data);
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true);
      lh.setUint16(8, 0, true); lh.setUint16(10, dosTime, true); lh.setUint16(12, dosDate, true);
      lh.setUint32(14, crc, true); lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true);
      lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
      parts.push(new Uint8Array(lh.buffer), name, data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true);
      ch.setUint16(8, 0x0800, true); ch.setUint16(10, 0, true); ch.setUint16(12, dosTime, true);
      ch.setUint16(14, dosDate, true); ch.setUint32(16, crc, true); ch.setUint32(20, data.length, true);
      ch.setUint32(24, data.length, true); ch.setUint16(28, name.length, true); ch.setUint16(30, 0, true);
      ch.setUint16(32, 0, true); ch.setUint16(34, 0, true); ch.setUint16(36, 0, true);
      ch.setUint32(38, 0, true); ch.setUint32(42, offset, true);
      central.push(new Uint8Array(ch.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const cdSize = central.reduce((n, p) => n + p.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, new Uint8Array(end.buffer)],
      { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }

  // ------------------------------------------------------------ spreadsheet parts
  const colName = i => { let s = ""; i++; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; };
  const excelDate = iso => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return null;
    return (Date.UTC(+m[1], +m[2] - 1, +m[3]) - Date.UTC(1899, 11, 30)) / 86400000;
  };
  // Style indexes (see STYLES): 0 normal, 1 header, 2 date, 3 wrapped, 4 hyperlink, 5 title
  const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="mmm d, yyyy"/></numFmts>
<fonts count="4">
<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
<font><u/><sz val="11"/><color rgb="FF1F5FA8"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="13"/><color rgb="FF1F3A5F"/><name val="Calibri"/><family val="2"/></font>
</fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F3A5F"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="left" vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

  function sheetXml(sheet) {
    const cols = sheet.columns, links = [];
    const pre = sheet.title ? 2 : 0;          // optional title row + blank row
    const headerRow = pre + 1;
    let rowsXml = "";
    if (sheet.title) {
      rowsXml += `<row r="1"><c r="A1" t="inlineStr" s="5"><is><t xml:space="preserve">${xmlEsc(sheet.title)}</t></is></c></row>`;
    }
    rowsXml += `<row r="${headerRow}" ht="20" customHeight="1">` + cols.map((c, i) =>
      `<c r="${colName(i)}${headerRow}" t="inlineStr" s="1"><is><t>${xmlEsc(c.header)}</t></is></c>`).join("") + "</row>";
    sheet.rows.forEach((row, ri) => {
      const r = headerRow + 1 + ri;
      rowsXml += `<row r="${r}">`;
      cols.forEach((c, ci) => {
        const ref = `${colName(ci)}${r}`;
        let v = row[ci];
        if (v === null || v === undefined || v === "") return;
        if (c.type === "date") {
          const n = excelDate(v);
          if (n !== null) { rowsXml += `<c r="${ref}" s="2"><v>${n}</v></c>`; return; }
        }
        if (c.type === "number" && v !== "" && !isNaN(+v)) { rowsXml += `<c r="${ref}"><v>${+v}</v></c>`; return; }
        if (c.type === "link" && v && typeof v === "object") {
          if (v.url) links.push({ ref, url: v.url });
          rowsXml += `<c r="${ref}" t="inlineStr" s="${v.url ? 4 : 0}"><is><t xml:space="preserve">${xmlEsc(v.text)}</t></is></c>`;
          return;
        }
        if (Array.isArray(v)) v = v.join("; ");
        const s = c.type === "wrap" ? 3 : 0;
        rowsXml += `<c r="${ref}" t="inlineStr" s="${s}"><is><t xml:space="preserve">${xmlEsc(String(v).slice(0, 32000))}</t></is></c>`;
      });
      rowsXml += "</row>";
    });
    const lastCol = colName(cols.length - 1), lastRow = headerRow + Math.max(sheet.rows.length, 1);
    const colsXml = "<cols>" + cols.map((c, i) => `<col min="${i + 1}" max="${i + 1}" width="${c.width || 14}" customWidth="1"/>`).join("") + "</cols>";
    const pane = `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${headerRow}" topLeftCell="A${headerRow + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`;
    const linksXml = links.length ? "<hyperlinks>" + links.map((l, i) => `<hyperlink ref="${l.ref}" r:id="rId${i + 1}"/>`).join("") + "</hyperlinks>" : "";
    const xml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
${pane}<sheetFormatPr defaultRowHeight="15"/>${colsXml}<sheetData>${rowsXml}</sheetData>
<autoFilter ref="A${headerRow}:${lastCol}${lastRow}"/>${linksXml}
<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>
<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>`;
    const rels = links.length ? `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      links.map((l, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="${xmlEsc(l.url)}" TargetMode="External"/>`).join("") +
      "</Relationships>" : null;
    return { xml, rels, headerRow, lastCol, lastRow };
  }

  function build(sheets) {
    const files = [], built = sheets.map(sheetXml);
    const safeName = (n, i) => (String(n || `Sheet${i + 1}`).replace(/[\[\]\*\?\/\\:]/g, " ").slice(0, 31)) || `Sheet${i + 1}`;
    files.push({ name: "[Content_Types].xml", data: enc.encode(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
${sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("\n")}
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>`) });
    files.push({ name: "_rels/.rels", data: enc.encode(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>`) });
    files.push({ name: "docProps/core.xml", data: enc.encode(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Kansas Legislation Tracker export</dc:title><dc:creator>Kansas Legislation Tracker</dc:creator>
<dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString().replace(/\.\d+Z$/, "Z")}</dcterms:created>
</cp:coreProperties>`) });
    files.push({ name: "xl/workbook.xml", data: enc.encode(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>${sheets.map((s, i) => `<sheet name="${xmlEsc(safeName(s.name, i))}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets>
<definedNames>${built.map((b, i) => `<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">'${xmlEsc(safeName(sheets[i].name, i)).replace(/'/g, "''")}'!$A$${b.headerRow}:$${b.lastCol}$${b.lastRow}</definedName>`).join("")}</definedNames>
</workbook>`) });
    files.push({ name: "xl/_rels/workbook.xml.rels", data: enc.encode(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
${sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("\n")}
<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`) });
    files.push({ name: "xl/styles.xml", data: enc.encode(STYLES) });
    built.forEach((b, i) => {
      files.push({ name: `xl/worksheets/sheet${i + 1}.xml`, data: enc.encode(b.xml) });
      if (b.rels) files.push({ name: `xl/worksheets/_rels/sheet${i + 1}.xml.rels`, data: enc.encode(b.rels) });
    });
    return zip(files);
  }

  function download(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }

  global.XlsxWriter = { build, download, zip };
})(window);
