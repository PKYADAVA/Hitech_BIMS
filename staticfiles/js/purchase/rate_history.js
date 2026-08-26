/* ---------------------------------------------------------------------------
   What an item last cost, shown beside the row being priced.

   Entering a purchase means judging whether the rate on the invoice in front of
   you is reasonable, and the only way to check was to abandon the half-typed
   form and open the register.

   Two groups, because they answer different questions. What the supplier on
   this bill charged last time settles an argument with them; what everyone else
   charged says whether to be having it. A single merged list would usually bury
   whichever mattered - buy mostly from one supplier and rival prices never
   surface, buy around and the supplier's own last rate falls off the end.

   Shared by both purchase forms. They disagree about where the item lives - the
   general form has one per row, the chicks form one on the header - so each
   page wires its own change handlers and calls show(). Everything after that,
   including which supplier to compare against, is the same on both.

   Markup expected on the page:
     <div id="rate-history"></div>     where the strip renders
     [name=supplier]                   the supplier being bought from
   --------------------------------------------------------------------------- */
window.RateHistory = (function () {
  const ENDPOINT = '/general-purchase/item-rates/';

  // Only the newest reply may render. Picking two items quickly otherwise
  // leaves whichever reply lands last on screen, which need not be the one for
  // the item now selected.
  let token = 0;
  let current = { id: '', name: '' };

  function box() { return document.getElementById('rate-history'); }

  function supplierId() {
    const el = document.querySelector('[name=supplier]');
    return el ? (el.value || '') : '';
  }

  function chip(r, withName) {
    const el = document.createElement('span');
    el.className = 'rate-chip';
    const rate = document.createElement('b');
    rate.textContent = '₹' + r.rate;
    const when = document.createElement('span');
    when.className = 'rate-chip-when';
    // textContent throughout: a supplier name with < or & cannot inject markup.
    when.textContent = ' · ' + r.date + (withName && r.supplier ? ' · ' + r.supplier : '');
    el.append(rate, when);
    el.title = [r.supplier, r.purchase_no, r.qty ? (r.qty + ' ' + r.unit).trim() : '']
               .filter(Boolean).join('  ·  ');
    return el;
  }

  function group(host, label, rows, opts) {
    opts = opts || {};
    const head = document.createElement('span');
    head.className = 'rate-history-label';
    head.textContent = label;
    host.append(head);
    if (!rows.length) {
      const none = document.createElement('span');
      none.className = 'rate-history-none';
      none.textContent = opts.empty || 'none';
      host.append(none);
      return;
    }
    // Against the chosen supplier the name is already the heading, so repeating
    // it on every chip is noise; the other group needs it on each.
    rows.forEach(r => host.append(chip(r, !!opts.withName)));
  }

  async function show(itemId, itemName) {
    const host = box();
    if (!host) return;
    current = { id: itemId || '', name: itemName || (itemId ? current.name : '') };
    const mine = ++token;
    if (!itemId) { host.innerHTML = ''; return; }

    host.innerHTML = '<span class="rate-history-none">loading…</span>';
    let data;
    try {
      const res = await fetch(ENDPOINT + '?item=' + encodeURIComponent(itemId) +
                              '&supplier=' + encodeURIComponent(supplierId()));
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (err) {
      if (mine !== token) return;
      host.innerHTML = '<span class="rate-history-none">Could not load earlier rates.</span>';
      return;
    }
    if (mine !== token) return;             // a newer pick won

    host.innerHTML = '';
    if (current.name) {
      const name = document.createElement('span');
      name.className = 'rate-history-item';
      name.textContent = current.name;
      host.append(name);
    }
    if (data.supplier) {
      group(host, data.supplier, data.same, { empty: 'not bought from them before' });
      group(host, 'Others', data.others, { withName: true });
    } else {
      group(host, 'Last purchases', data.others,
            { withName: true, empty: 'none recorded yet' });
    }
  }

  // Both lists are relative to the supplier on the bill, so a change of
  // supplier re-asks for the item already on screen rather than leaving the
  // last supplier's comparison sitting under the new one's name.
  function refresh() {
    if (current.id) show(current.id, current.name);
  }

  return { show, refresh };
})();
