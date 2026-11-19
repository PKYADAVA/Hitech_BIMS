/* Shared GST print format for the hatchery transaction documents —
   Delivery Challan and Chick Sale (chicks sale bill).

   Both documents print the same statutory tax-invoice form: letterhead,
   party/document boxes, a ruled item grid, an HSN/SAC tax summary, amount
   and tax in words, bank details and the signature block. The pieces that
   differ between the two (which columns the item grid carries, what the
   totals mean) are passed in; everything that must look identical on paper
   lives here, so the two cannot drift apart.

   Window-scoped (no module system on these pages), matching main.js. */
(function (w) {
  "use strict";

  function esc(v) {
    return String(v === null || v === undefined ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }

  /** 1234567.5 -> "12,34,567.50" (Indian grouping, as the rest of the ERP shows money). */
  function money(v) {
    return num(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /** Trailing zeros dropped, so a whole-number quantity prints "500", not "500.00". */
  function qty(v) {
    var n = Math.round(num(v) * 100) / 100;
    return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }

  var ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
  var TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

  function two(n) { return n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? " " + ONES[n % 10] : ""); }

  function three(n) {
    var s = "";
    if (n >= 100) { s += ONES[Math.floor(n / 100)] + " Hundred"; n %= 100; if (n) s += " "; }
    if (n) s += two(n);
    return s;
  }

  /** Indian-system words for a whole number: 112233 -> "One Lakh Twelve Thousand Two Hundred Thirty Three". */
  function wordsForInt(n) {
    n = Math.floor(Math.abs(num(n)));
    if (!n) return "Zero";
    var parts = [];
    var crore = Math.floor(n / 10000000); n %= 10000000;
    var lakh = Math.floor(n / 100000); n %= 100000;
    var thousand = Math.floor(n / 1000); n %= 1000;
    // Past 999 crore the crore count itself needs the full Indian grouping.
    if (crore) parts.push((crore > 999 ? wordsForInt(crore) : three(crore)) + " Crore");
    if (lakh) parts.push(two(lakh) + " Lakh");
    if (thousand) parts.push(two(thousand) + " Thousand");
    if (n) parts.push(three(n));
    return parts.join(" ");
  }

  /** "SIX HUNDRED EIGHTY FOUR RUPEES AND NINETY PAISA ONLY" — paise included
      when there are any, which the tax line almost always has. */
  function rupeesInWords(value) {
    var v = Math.round(num(value) * 100) / 100;
    var rupees = Math.floor(v);
    var paise = Math.round((v - rupees) * 100);
    var s = wordsForInt(rupees) + " Rupee" + (rupees === 1 ? "" : "s");
    if (paise) s += " and " + wordsForInt(paise) + " Paisa";
    return (s + " Only").toUpperCase();
  }

  /** A GSTIN's first two digits are its state code: "32AABBA7890B1ZB" -> "32". */
  function stateCode(gstin) {
    var m = /^\s*(\d{2})/.exec(String(gstin || ""));
    return m ? m[1] : "";
  }

  function normState(s) { return String(s || "").trim().toLowerCase(); }

  /**
   * Intra-state (CGST+SGST) or inter-state (IGST)?
   *
   * Decided on the GSTIN state codes when both sides have one, since that is
   * the authoritative pair; otherwise on the state names. Unknown falls back
   * to intra-state, the common case for a hatchery selling locally, and in
   * either case the total tax charged is the same — only its split differs.
   */
  function isInterState(company, customerState, customerGstin, placeOfSupply) {
    var ours = stateCode(company && company.gstin);
    var theirs = stateCode(customerGstin);
    if (ours && theirs) return ours !== theirs;
    var a = normState(company && company.state);
    var b = normState(placeOfSupply) || normState(customerState);
    if (!a || !b) return false;
    return a !== b;
  }

  /**
   * Per-HSN tax summary — the block the statutory format carries under the
   * item grid. Lines are grouped by HSN and rate, so two items on the same
   * HSN at the same rate print as one row, as a GST bill is expected to.
   *
   * `lines` are {hsn, taxable, taxPercent}; the caller supplies the taxable
   * value because the two documents compute it differently.
   */
  function hsnSummary(lines, inter) {
    var byKey = {};
    var order = [];
    (lines || []).forEach(function (l) {
      var hsn = String(l.hsn || "").trim() || "—";
      var rate = Math.round(num(l.taxPercent) * 100) / 100;
      var key = hsn + "|" + rate;
      if (!byKey[key]) { byKey[key] = { hsn: hsn, rate: rate, taxable: 0 }; order.push(key); }
      byKey[key].taxable += num(l.taxable);
    });
    return order.map(function (k) {
      var r = byKey[k];
      var tax = r.taxable * r.rate / 100;
      return {
        hsn: r.hsn, rate: r.rate, taxable: r.taxable,
        // Halved for the CGST/SGST pair so the two columns add back to `tax`.
        cgst: inter ? 0 : tax / 2, sgst: inter ? 0 : tax / 2,
        igst: inter ? tax : 0, tax: tax
      };
    });
  }

  /** The HSN/SAC summary table, with the grouped CGST+SGST / GST header.
      Skipped entirely when no line carries tax — an all-zero block is a
      statutory table saying nothing, and the documents here are often
      raised for exempt/nil-rated supply (day-old chicks). */
  function hsnSummaryHtml(rows, inter) {
    if (!rows || !rows.length) return "";
    if (!rows.some(function (r) { return num(r.tax) > 0; })) return "";
    var totals = rows.reduce(function (t, r) {
      t.taxable += r.taxable; t.cgst += r.cgst; t.sgst += r.sgst; t.igst += r.igst; t.tax += r.tax;
      return t;
    }, { taxable: 0, cgst: 0, sgst: 0, igst: 0, tax: 0 });

    var head = inter
      ? '<th class="num" colspan="2">GST</th>'
      : '<th class="num" colspan="2">CGST</th><th class="num" colspan="2">SGST</th>';
    var sub = inter
      ? '<th class="num">%</th><th class="num">Amount</th>'
      : '<th class="num">%</th><th class="num">Amount</th><th class="num">%</th><th class="num">Amount</th>';

    var body = rows.map(function (r) {
      var half = Math.round(r.rate / 2 * 100) / 100;
      var cells = inter
        ? '<td class="num">' + r.rate.toFixed(2) + '</td><td class="num">' + money(r.igst) + '</td>'
        : '<td class="num">' + half.toFixed(2) + '</td><td class="num">' + money(r.cgst) + '</td>'
          + '<td class="num">' + half.toFixed(2) + '</td><td class="num">' + money(r.sgst) + '</td>';
      return '<tr><td>' + esc(r.hsn) + '</td><td class="num">' + money(r.taxable) + '</td>'
        + cells + '<td class="num">' + money(r.tax) + '</td></tr>';
    }).join("");

    var footCells = inter
      ? '<td class="num"></td><td class="num">' + money(totals.igst) + '</td>'
      : '<td class="num"></td><td class="num">' + money(totals.cgst) + '</td>'
        + '<td class="num"></td><td class="num">' + money(totals.sgst) + '</td>';

    return '<div class="hsn-wrap"><table class="hsn-table"><thead>'
      + '<tr><th rowspan="2">HSN / SAC</th><th class="num" rowspan="2">Taxable Value</th>'
      + head + '<th class="num" rowspan="2">Total</th></tr>'
      + '<tr>' + sub + '</tr></thead><tbody>' + body
      + '<tr class="total-row"><td class="num">Total</td><td class="num">' + money(totals.taxable) + '</td>'
      + footCells + '<td class="num">' + money(totals.tax) + '</td></tr>'
      + '</tbody></table>'
      + '<div class="tax-words">Total Tax in words: <b>' + esc(rupeesInWords(totals.tax)) + '</b></div>'
      + '</div>';
  }

  /** Letterhead: logo, company name, address, and the statutory GSTIN line. */
  /**
   * Letterhead, laid out as the statutory bill does it: company name large on
   * the left with its line of business under it, logo on the right, then the
   * address on the left against the phone/web/email block on the right.
   * Below that the title band — GSTIN on the left, document name centred, copy
   * marking on the right.
   */
  function headerHtml(company, docTitle, copyLabel) {
    company = company || {};

    // Most saved addresses already end with the state; appending it blindly
    // printed "Uttar Pradesh, Uttar Pradesh" on the letterhead.
    var address = String(company.address || "");
    var state = String(company.state || "").trim();
    if (state && normState(address).indexOf(normState(state)) === -1) {
      address = address.replace(/[\s,]+$/, "") + ", " + state;
    }

    var right = [];
    if (company.mobile) right.push("Tel : " + esc(company.mobile));
    if (company.website) right.push("Web : " + esc(company.website));
    if (company.email) right.push("Email : " + esc(company.email));

    return '<div class="letterhead">'
      + '<div class="lh-name">'
      + '<h4>' + esc(company.name) + '</h4>'
      + (company.tagline ? '<div class="lh-tagline">' + esc(company.tagline) + '</div>' : "")
      + '</div>'
      + (company.logo_url
        ? '<div class="lh-logo"><img src="' + esc(company.logo_url) + '" alt=""></div>' : "")
      + '</div>'
      + '<div class="lh-contact">'
      + '<div class="lh-addr">' + esc(address).replace(/\n/g, "<br>") + '</div>'
      + '<div class="lh-right">' + right.join("<br>") + '</div>'
      + '</div>'
      + '<div class="doc-title-bar">'
      + '<div class="dt-left">'
      + (company.gstin ? 'GSTIN : <b>' + esc(company.gstin) + '</b>' : "") + '</div>'
      + '<div class="dt-mid">' + esc(docTitle) + '</div>'
      + '<div class="dt-right">' + esc(copyLabel || "ORIGINAL FOR RECIPIENT") + '</div>'
      + '</div>';
  }

  /**
   * The closing block, laid out as the statutory bill does: bank details on
   * the left against the certification/signature panel on the right, then a
   * full-width terms row with the customer's own signature box.
   */
  function footerHtml(company, terms, extraNote) {
    company = company || {};
    var bank = [
      ["Name", company.bank_name], ["Branch", company.bank_branch],
      ["Acc. Number", company.bank_account_no], ["IFSC", company.ifsc_code],
      ["UPI ID", company.upi_id]
    ].filter(function (p) { return p[1]; });

    var html = '<div class="pay-band">'
      + '<div class="pb-bank">'
      + '<div class="pb-head">Bank Details</div>'
      + (bank.length
        ? '<table class="pb-table">' + bank.map(function (p) {
          return '<tr><th>' + esc(p[0]) + '</th><td>' + esc(p[1]) + '</td></tr>';
        }).join("") + '</table>'
        : '<div class="muted">-</div>')
      + '</div>'
      + '<div class="pb-sign">'
      + '<div class="certify">Certified that the particulars given above are true and correct.</div>'
      + '<div class="for-co">For ' + esc(company.name) + '</div>'
      + (extraNote ? '<div class="cg-note">' + extraNote + '</div>' : "")
      + '<div class="signature-line">Authorised Signatory</div>'
      + '</div></div>';

    html += '<div class="terms-band">'
      + '<div class="tb-terms">'
      + '<div class="pb-head">Terms and Conditions</div>'
      + '<div class="tb-body">' + (terms ? esc(terms).replace(/\n/g, '<br>') : '-') + '</div>'
      + '<div class="cust-sign">Customer Signature</div>'
      + '</div></div>';
    return html;
  }

  /**
   * The band under the title: the two receiver boxes side by side, and the
   * document's own fields in a third column. `meta` is [label, value] pairs;
   * blanks are dropped so a challan without an e-way bill doesn't print an
   * empty row.
   */
  function partyRowsHtml(party) {
    return [
      ["Name", party.name],
      ["Address", party.address],
      ["Phone No.", party.mobile],
      ["State", party.state],
      ["GSTIN/UIN", party.gstin]
    ].map(function (r) {
      // Blank rows are kept rather than dropped: the two boxes sit beside
      // each other and the eye reads across them, so a missing Phone on one
      // side would slide its remaining rows up out of step with the other.
      return '<tr><th>' + esc(r[0]) + '</th><td>'
        + esc(r[1] || "").replace(/\n/g, '<br>') + '</td></tr>';
    }).join("");
  }

  /**
   * The document's own identity -- its number and date -- in a box of its
   * own above the party boxes, where the statutory form puts it. It used to
   * sit in the right-hand column among the transport rows, which buried the
   * one pair of fields the document is filed and found by.
   */
  function docIdBandHtml(rows) {
    var kept = (rows || []).filter(function (r) { return String(r[1] || "").trim(); });
    if (!kept.length) return "";

    // Split across two columns rather than one tall list. The band sits above
    // the party boxes and runs the full width of the page: a single column
    // left most of that width empty while the rows ran down past the boxes
    // beside them.  Filled column-wise, so reading down the left and then the
    // right follows the order the fields were given in.
    var half = Math.ceil(kept.length / 2);
    var cols = [kept.slice(0, half), kept.slice(half)];

    return '<div class="doc-id-band">'
      + cols.map(function (col) {
        return '<div class="dib-box"><table class="pb-table">'
          + col.map(function (r) {
            return '<tr><th>' + esc(r[0]) + '</th><td>: ' + esc(r[1]) + '</td></tr>';
          }).join("")
          + '</table></div>';
      }).join("")
      + '</div>';
  }

  /** The supply state, named once under the boxes as the form has it. */
  function placeOfSupplyHtml(placeOfSupply) {
    var v = String(placeOfSupply || "").trim();
    return v ? '<div class="pos-line">Place Of Supply : <b>' + esc(v) + '</b></div>' : "";
  }

  function partyBlockHtml(party, meta, shipTo) {
    var metaRows = (meta || []).filter(function (r) { return String(r[1] || "").trim(); });

    // Both boxes always, even when the goods go to the billing address and
    // the two read the same. The statutory form has a fixed shape and is
    // read by people checking one box against the other; dropping the second
    // when it matches made the document change shape from one consignment to
    // the next, and left a reader wondering whether a consignee had been
    // recorded at all. Where no separate address was entered the delivery is
    // to the buyer, so the buyer's own details fill it.
    var ship = shipTo && String(shipTo.address || "").trim() ? shipTo : party;

    // The third column only exists when the caller still has document fields
    // to put there. The challan's moved up into the band above, so its two
    // receiver boxes share the full width instead of leaving an empty panel
    // ruled off beside them.
    return '<div class="party-band has-ship' + (metaRows.length ? '' : ' no-meta') + '">'
      + '<div class="pb-customer">'
      + '<div class="pb-head">Details of Receiver (Buyer Detail)</div>'
      + '<table class="pb-table">' + partyRowsHtml(party) + '</table></div>'
      + '<div class="pb-ship">'
      + '<div class="pb-head">Details of Consignee (Shipped Detail)</div>'
      + '<table class="pb-table">' + partyRowsHtml(ship) + '</table></div>'
      + (metaRows.length
        ? '<div class="pb-meta"><table class="pb-table">'
          + metaRows.map(function (r) {
            return '<tr><th>' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td></tr>';
          }).join("")
          + '</table></div>'
        : '')
      + '</div>';
  }

  /* ----- The two documents ------------------------------------------
     Both list and form screens render through these, so a document looks
     the same however it was printed. `fmtDate` is supplied by the page
     (main.js) and falls back to the raw value when absent. */
  /** "CODE - Description", or whichever of the two is present. The form
      screens pass only the code (the option's own label already reads
      "CODE - Description"), so joining blindly left a trailing dash. */
  function itemName(row) {
    var code = String(row.item_code || "").trim();
    var desc = String(row.item_description || "").trim();
    if (code && desc) return "<b>" + esc(code) + "</b> - " + esc(desc);
    return "<b>" + esc(code || desc) + "</b>";
  }

  function fmtDate(v) {
    if (!v) return "";
    if (typeof w.fmtDate === "function" && w.fmtDate !== fmtDate) return w.fmtDate(v);
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
    return m ? m[3] + "-" + m[2] + "-" + m[1] : String(v);
  }

  /**
   * The open space below the items.
   *
   * One tall row, not a stack of short ones: each row draws its own cell
   * borders, and at print scale those round to slightly different positions,
   * which broke the column lines into visible segments. A single row gives
   * one unbroken rule per column, which is what the statutory form shows.
   */
  function fillerRowsHtml(cols) {
    return '<tr class="pad-row">' + "<td>&nbsp;</td>".repeat(cols) + '</tr>';
  }

  function renderChallanViewHtml(c) {
    const priceCols = c.print_price_details;
    const company = c.company || {};
    const discount = num(c.overall_discount);
    const grandTotal = num(c.grand_total);
    const totalTax = num(c.total_tax);
    const taxableValue = grandTotal - totalTax + discount;
    const inter = isInterState(company, c.customer_state, c.customer_gstin, c.place_of_supply);

    let html = headerHtml(company, "Delivery Challan", "ORIGINAL FOR RECIPIENT");

    // The document's own fields, all of them, in the band above the party
    // boxes: its number and date, then how the consignment travelled. They
    // had been split, the number and date here and the transport rows down
    // the side of the party boxes, which left the carrier's details reading
    // as part of the consignee rather than as the document's own.
    html += docIdBandHtml([
      ["Challan Number", c.challan_no],
      ["Challan Date", fmtDate(c.date)],
      ["Transport Doc No.", c.transport_document_no],
      ["Transport Doc Date", c.transport_document_date ? fmtDate(c.transport_document_date) : ""],
      ["E-Way Bill No.", c.eway_bill_no],
      ["E-Way Bill Date", c.eway_bill_date ? fmtDate(c.eway_bill_date) : ""],
      // How the goods travelled. The form asks for it -- Road, Rail, Air or
      // Courier -- and it belongs on the challan the driver carries, but it
      // was the one Transportation Details field the document never printed.
      ["Transport Mode", c.transport_mode],
      ["Transporter", c.transporter_name],
      ["Vehicle No.", c.vehicle_no],
      ["Driver", c.driver_name],
      ["Driver Mobile", c.driver_mobile],
    ]);

    html += partyBlockHtml({
      name: c.customer_name,
      address: c.customer_address,
      mobile: c.customer_mobile,
      gstin: c.customer_gstin,
      state: c.place_of_supply || c.customer_state,
    }, [], {
      // Same party, different address: a delivery elsewhere is still the
      // customer's consignment, so the name and GSTIN carry over.
      name: c.customer_name,
      address: c.shipping_address,
      mobile: c.customer_mobile,
      gstin: c.customer_gstin,
      state: c.place_of_supply || c.customer_state,
    });

    html += placeOfSupplyHtml(c.place_of_supply || c.customer_state);

    // Columns follow the statutory grid: the tax columns sit inside it under a
    // grouped CGST+SGST / GST header, and each line closes with its own Total
    // (taxable + tax) rather than leaving tax to the summary alone.
    const taxCols = inter ? 2 : 4;
    const colCount = priceCols ? 6 + taxCols : 5;
    html += `<div class="items-wrap"><table><thead>`;
    if (priceCols) {
      html += `<tr>
        <th class="ds-mid" rowspan="2">Sr. No.</th><th rowspan="2">Name of Product / Service</th>
        <th rowspan="2">HSN / SAC</th><th class="num" rowspan="2">Qty</th>
        <th class="num" rowspan="2">Rate</th><th class="num" rowspan="2">Taxable Value</th>
        ${inter ? '<th class="num" colspan="2">GST</th>'
                : '<th class="num" colspan="2">CGST</th><th class="num" colspan="2">SGST</th>'}
        <th class="num" rowspan="2">Total</th>
      </tr><tr>
        ${inter ? '<th class="num">%</th><th class="num">Amount</th>'
                : '<th class="num">%</th><th class="num">Amount</th><th class="num">%</th><th class="num">Amount</th>'}
      </tr>`;
    } else {
      html += `<tr><th class="ds-mid">Sr. No.</th><th>Name of Product / Service</th>
        <th>HSN / SAC</th><th class="num">Qty</th><th>Unit</th></tr>`;
    }
    html += `</thead><tbody>`;

    // Taxable value per line, the base the tax columns and the summary agree
    // on: qty x rate less the line discount, before tax.
    const taxLines = [];
    let sumTaxable = 0, sumTax = 0;
    (c.items || []).forEach((row, i) => {
      const discPct = num(row.discount_percent), taxPct = num(row.tax_percent);
      // The flat discount beside the percentage one, either off the whole
      // line or off each unit. Both come off before tax, the same order the
      // entry form works the amount out in, so the printed bill and the
      // saved record agree.
      const flatDisc = row.discount_basis === "unit"
        ? num(row.discount_amount) * num(row.quantity)
        : num(row.discount_amount);
      const lineTaxable = Math.max(
        num(row.quantity) * num(row.price) * (1 - discPct / 100) - flatDisc, 0);
      const lineTax = lineTaxable * taxPct / 100;
      const half = Math.round(taxPct / 2 * 100) / 100;
      sumTaxable += lineTaxable; sumTax += lineTax;
      taxLines.push({ hsn: row.hsn_code, taxable: lineTaxable, taxPercent: taxPct });
      const qtyCell = `${qty(row.quantity)}${row.unit ? " " + esc(row.unit) : ""}`;
      html += `<tr><td>${i + 1}</td><td>${itemName(row)}</td><td>${esc(row.hsn_code) || "-"}</td>`;
      html += priceCols
        ? `<td class="num">${qtyCell}</td><td class="num">${money(row.price)}</td>`
          + `<td class="num">${money(lineTaxable)}</td>`
          + (inter
            ? `<td class="num">${taxPct.toFixed(2)}</td><td class="num">${money(lineTax)}</td>`
            : `<td class="num">${half.toFixed(2)}</td><td class="num">${money(lineTax / 2)}</td>`
              + `<td class="num">${half.toFixed(2)}</td><td class="num">${money(lineTax / 2)}</td>`)
          + `<td class="num">${money(lineTaxable + lineTax)}</td>`
        : `<td class="num">${qty(row.quantity)}</td><td>${esc(row.unit)}</td>`;
      html += `</tr>`;
    });

    html += fillerRowsHtml(colCount);

    const totalQty = (c.items || []).reduce((s, r) => s + num(r.quantity), 0);
    html += `<tr class="total-row"><td colspan="3">Total</td><td class="num">${qty(totalQty)}</td>`;
    html += priceCols
      ? `<td></td><td class="num">${money(sumTaxable)}</td>`
        + (inter
          ? `<td></td><td class="num">${money(sumTax)}</td>`
          : `<td></td><td class="num">${money(sumTax / 2)}</td><td></td><td class="num">${money(sumTax / 2)}</td>`)
        + `<td class="num">${money(sumTaxable + sumTax)}</td>`
      : `<td></td>`;
    html += `</tr></tbody></table></div>`;

    if (priceCols) {
      // Words on the left, the tax summary boxed at the right, as the bill has it.
      html += `<div class="words-band">
        <div class="wb-left">
          <div class="wb-label">Total in words</div>
          <div class="wb-words">${esc(rupeesInWords(grandTotal))}</div>
          <div class="wb-eoe">(E &amp; O.E.)</div>
        </div>
        <div class="wb-sum">
          <div><span>Taxable Amount</span><b>${money(sumTaxable)}</b></div>
          ${discount ? `<div><span>Discount</span><b>(-) ${money(discount)}</b></div>` : ""}
          <div><span>Add : ${inter ? "GST" : "CGST + SGST"}</span><b>${money(sumTax)}</b></div>
          <div><span>Total Tax</span><b>${money(sumTax)}</b></div>
          <div class="grand"><span>Total Amount After Tax</span><b>&#8377; ${money(grandTotal)}</b></div>
        </div>
      </div>`;
      html += hsnSummaryHtml(hsnSummary(taxLines, inter), inter);
    }

    html += footerHtml(company, c.terms, "This is a computer generated delivery challan.");
    return html;
  }

  function renderSaleViewHtml(cs) {
    const company = cs.company || {};
    const finalAmount = num(cs.final_amount);
    const freightAmount = num(cs.freight_amount);
    const billedFreight = cs.freight_type === "Include in Bill" ? freightAmount : 0;
    const itemsAmount = (cs.items || []).reduce((s, r) => s + num(r.amount), 0);
    const inter = isInterState(company, cs.customer_state, cs.customer_gstin, "");

    let html = headerHtml(company, "Tax Invoice", "ORIGINAL FOR RECIPIENT");

    html += docIdBandHtml([
      ["Invoice Number", cs.bill_no],
      ["Invoice Date", fmtDate(cs.date)],
      ["Challan No.", cs.dc_no],
      ["Stock Point", cs.warehouse_name],
      ["Vehicle", cs.vehicle],
      ["Driver", cs.driver],
      ["Freight", cs.freight_type],
      ["Payment", cs.payment_mode === "pay_in_bill" ? "Paid" : (cs.payment_mode ? "Credit" : "")],
    ]);

    html += partyBlockHtml({
      name: cs.customer_name,
      address: cs.customer_address,
      mobile: cs.customer_mobile,
      gstin: cs.customer_gstin,
      state: cs.customer_state,
    }, [], {
      name: cs.customer_name,
      address: cs.shipping_address,
      mobile: cs.customer_mobile,
      gstin: cs.customer_gstin,
      state: cs.customer_state,
    });

    html += placeOfSupplyHtml(cs.customer_state);

    const COLS = 8;
    html += `<div class="items-wrap"><table><thead><tr>
      <th class="ds-mid">Sr. No.</th><th>Name of Product / Service</th><th>HSN / SAC</th>
      <th class="num">Qty</th><th class="num">Free Qty</th><th class="num">Billed Qty</th>
      <th class="num">Rate</th><th class="num">Amount (&#8377;)</th>
    </tr></thead><tbody>`;

    // Chick sale carries no per-line GST rate, so the HSN summary reports the
    // line value at a 0% rate rather than inventing one — the bill still shows
    // the statutory HSN breakdown without overstating tax that wasn't charged.
    const taxLines = [];
    (cs.items || []).forEach((row, i) => {
      taxLines.push({ hsn: row.hsn_code, taxable: num(row.amount), taxPercent: 0 });
      html += `<tr><td>${i + 1}</td><td>${itemName(row)}${row.farm ? `<br><small>Farm: ${esc(row.farm)}</small>` : ""}</td>`
        + `<td>${esc(row.hsn_code) || "-"}</td>`
        + `<td class="num">${qty(row.total_qty)}</td><td class="num">${qty(row.free_qty)}</td>`
        + `<td class="num">${qty(row.net_qty)}</td><td class="num">${money(row.sale_rate)}</td>`
        + `<td class="num">${money(row.amount)}</td></tr>`;
    });

    // Totals stacked inside the grid, as the statutory form does it.
    const sub = [["", money(itemsAmount)]];
    if (billedFreight) sub.push(["Freight", money(billedFreight)]);
    else if (freightAmount) sub.push(["Freight (paid by customer)", money(freightAmount)]);
    sub.forEach(([label, val], idx) => {
      html += `<tr class="sub-row${idx === 0 ? " first" : ""}"><td colspan="${COLS - 2}" class="noline"></td>`
        + `<td class="num lbl">${esc(label)}</td><td class="num">${val}</td></tr>`;
    });

    html += fillerRowsHtml(COLS);
    const totalNetQty = (cs.items || []).reduce((s, r) => s + num(r.net_qty), 0);
    html += `<tr class="total-row"><td colspan="5">Total</td><td class="num">${qty(totalNetQty)}</td>`
      + `<td></td><td class="num grand">&#8377; ${money(finalAmount)}</td></tr>`;
    html += `</tbody></table></div>`;

    // Words left, tax summary boxed right — the same close as the challan.
    // Chick sale carries no per-line GST, so the tax rows read zero rather
    // than being hidden: the bill still shows what was and wasn't charged.
    html += `<div class="words-band">
      <div class="wb-left">
        <div class="wb-label">Total in words</div>
        <div class="wb-words">${esc(rupeesInWords(finalAmount))}</div>
        <div class="wb-eoe">(E &amp; O.E.)</div>
      </div>
      <div class="wb-sum">
        <div><span>Taxable Amount</span><b>${money(itemsAmount)}</b></div>
        ${billedFreight ? `<div><span>Add : Freight</span><b>${money(billedFreight)}</b></div>` : ""}
        ${freightAmount && !billedFreight ? `<div><span>Freight (paid by customer)</span><b>${money(freightAmount)}</b></div>` : ""}
        <div class="grand"><span>Total Amount After Tax</span><b>&#8377; ${money(finalAmount)}</b></div>
      </div>
    </div>`;

    html += hsnSummaryHtml(hsnSummary(taxLines, inter), inter);

    html += footerHtml(company,
      cs.terms + (cs.remarks ? (cs.terms ? "\n" : "") + "Remarks: " + cs.remarks : ""),
      "This is a computer generated invoice.");
    return html;
  }

  w.GSTInvoice = {
    esc: esc, num: num, money: money, qty: qty,
    rupeesInWords: rupeesInWords, wordsForInt: wordsForInt,
    isInterState: isInterState, hsnSummary: hsnSummary, hsnSummaryHtml: hsnSummaryHtml,
    headerHtml: headerHtml, footerHtml: footerHtml,
    renderChallanViewHtml: renderChallanViewHtml, renderSaleViewHtml: renderSaleViewHtml
  };
  // Page code calls these by bare name.
  w.renderChallanViewHtml = renderChallanViewHtml;
  w.renderSaleViewHtml = renderSaleViewHtml;
})(window);
