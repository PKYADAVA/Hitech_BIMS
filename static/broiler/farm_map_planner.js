/* Farm Map & Route Planner — the browser half.
 *
 * Leaflet draws; the server decides. Nothing here works out a distance: every
 * kilometre on this screen came off a road network through
 * broiler.services.routing, because a straight line between two pins
 * understates a hill road by half and this page is what a travel claim is
 * settled against. When the server says the figures are estimates
 * (`estimated: true`, the straight-line fallback) the panel says so in as
 * many words rather than letting them pass as measurements.
 *
 * Route calculation is deliberate — a button, not a filter change. Providers
 * charge per call and a planner that recalculated on every keystroke would
 * cost money to think with.
 */
window.FarmMapPlanner = (function () {
  "use strict";

  var map = null;
  var markerLayer = null;
  var routeLayer = null;
  var farms = [];          // every mapped farm currently shown
  var missing = [];        // farms with no usable pin
  var selected = new Set();
  var plan = null;         // the last calculated route
  var startPoint = null;   // {label, latitude, longitude} — where the day begins
  var pickingStart = false;
  var startMarker = null;
  var labelLayer = null;   // farm names and leg distances, toggled together
  var baseLayers = {};     // street and satellite
  var page = 1;
  var PAGE_SIZE = 12;

  var PRIORITY_COLOUR = { critical: "#dc2626", high: "#ea580c", normal: "#2563eb" };
  var INACTIVE_COLOUR = "#94a3b8";

  // ---- small helpers ------------------------------------------------------

  function el(id) { return document.getElementById(id); }

  function esc(text) {
    // main.js publishes escapeHtml globally; fall back so this file also
    // works on a page that has not loaded it.
    if (window.escapeHtml) return window.escapeHtml(text);
    var d = document.createElement("div");
    d.textContent = text === null || text === undefined ? "" : String(text);
    return d.innerHTML;
  }

  function km(value) {
    return (value === null || value === undefined) ? "—" : Number(value).toFixed(1) + " km";
  }

  function hhmm(minutes) {
    if (minutes === null || minutes === undefined) return "—";
    var m = Math.round(Number(minutes));
    var h = Math.floor(m / 60);
    var rest = m % 60;
    if (h && rest) return h + "h " + String(rest).padStart(2, "0") + "m";
    return h ? h + "h" : rest + "m";
  }

  function csrf() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (field && field.value) return field.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  /* Read a reply that ought to be JSON, and say something useful when it is
     not. A 403 from the CSRF middleware is a page of HTML; parsing it throws,
     and reporting that as "check the network" sends somebody to look at their
     wifi over a missing token. */
  function readJson(response) {
    return response.text().then(function (body) {
      try {
        return { ok: response.ok, data: JSON.parse(body) };
      } catch (err) {
        return { ok: false, data: { error: response.status === 403
          ? "Your session has expired, or this page was left open too long. Reload and try again."
          : "The server returned an unexpected response (" + response.status + ")." } };
      }
    });
  }

  function notify(message, tone) {
    var box = el("fmp-alert");
    box.className = "alert alert-" + (tone || "info");
    box.innerHTML = message;
    box.classList.remove("d-none");
    if (tone === "success") {
      window.setTimeout(function () { box.classList.add("d-none"); }, 6000);
    }
  }

  function clearNotice() { el("fmp-alert").classList.add("d-none"); }

  // ---- map ----------------------------------------------------------------

  function pin(colour, label) {
    return L.divIcon({
      className: "",
      html: '<div class="fmp-pin" style="background:' + colour +
            ';width:1.35rem;height:1.35rem;color:#fff;font-size:.7rem;' +
            'display:flex;align-items:center;justify-content:center;">' +
            (label === undefined ? "" : label) + "</div>",
      iconSize: [22, 22], iconAnchor: [11, 11]
    });
  }

  function markerColour(farm) {
    if ((farm.status || "").toLowerCase() !== "active") return INACTIVE_COLOUR;
    return PRIORITY_COLOUR[farm.priority] || PRIORITY_COLOUR.normal;
  }

  function drawMarkers() {
    markerLayer.clearLayers();
    labelLayer.clearLayers();
    var bounds = [];
    farms.forEach(function (farm) {
      var stop = plan ? planStopFor(farm.id) : null;
      var marker = L.marker([farm.latitude, farm.longitude], {
        icon: pin(selected.has(farm.id) ? "#16a34a" : markerColour(farm),
                  stop ? stop.sequence : "")
      });
      marker.bindPopup(popupShell(farm), { minWidth: 250 });
      marker.on("popupopen", function () { fillPopup(farm, marker); });
      marker.addTo(markerLayer);
      // The name sits beside the pin permanently rather than on hover: a
      // planner is read to decide which farm to send somebody to, and a map of
      // anonymous dots cannot answer that.
      L.marker([farm.latitude, farm.longitude], {
        icon: L.divIcon({ className: "", html: '<span class="fmp-label">' +
                          esc(farm.name) + "</span>",
                          iconSize: [0, 0], iconAnchor: [-12, 8] }),
        interactive: false
      }).addTo(labelLayer);
      bounds.push([farm.latitude, farm.longitude]);
    });
    if (bounds.length && !plan) map.fitBounds(bounds, { padding: [30, 30] });
  }

  function planStopFor(farmId) {
    if (!plan) return null;
    return plan.stops.filter(function (s) { return s.farm_id === farmId; })[0] || null;
  }

  function popupShell(farm) {
    return '<div class="fmp-popup" data-farm="' + farm.id + '">' +
      '<div class="fw-semibold">' + esc(farm.name) + "</div>" +
      '<div class="small text-muted">' + esc(farm.code) + "</div>" +
      '<div class="small mt-1">' +
        "<div><b>Branch:</b> " + esc(farm.branch || "—") + "</div>" +
        "<div><b>Supervisor:</b> " + esc(farm.supervisor || "—") + "</div>" +
        "<div><b>Farmer:</b> " + esc(farm.farmer || "—") + "</div>" +
        "<div><b>Location:</b> " + esc(farm.location || "—") + "</div>" +
        "<div><b>Active batches:</b> " + esc(farm.active_batches) + "</div>" +
      "</div>" +
      '<div class="small mt-2 fmp-popup-batch text-muted">Loading flock…</div>' +
      '<div class="d-flex gap-1 flex-wrap mt-2">' +
        '<a class="btn btn-sm btn-outline-primary" href="' + window.FMP_URLS.farm + '">View Farm</a>' +
        '<button class="btn btn-sm btn-outline-success fmp-pick" data-farm="' + farm.id + '">' +
          (selected.has(farm.id) ? "Remove" : "Add to route") + "</button>" +
        '<a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" ' +
          'href="https://www.google.com/maps/dir/?api=1&destination=' +
          farm.latitude + "," + farm.longitude + '">Navigate</a>' +
      "</div></div>";
  }

  function fillPopup(farm, marker) {
    var url = window.FMP_URLS.batch.replace(/0\/batch\/$/, farm.id + "/batch/");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var node = marker.getPopup().getElement();
        if (!node) return;
        var box = node.querySelector(".fmp-popup-batch");
        if (!box) return;
        if (!data.batches || !data.batches.length) {
          box.innerHTML = "No active flock." +
            (data.last_visit ? "<br><b>Last visit:</b> " +
             esc(new Date(data.last_visit).toLocaleDateString()) : "");
          return;
        }
        box.innerHTML = data.batches.map(function (b) {
          return '<div class="border-top pt-1 mt-1">' +
            "<div><b>Batch:</b> " + esc(b.batch_no) + "</div>" +
            "<div><b>Age:</b> " + esc(b.age === null ? "—" : b.age + " days") + "</div>" +
            "<div><b>Bird type:</b> " + esc(b.bird_type || "—") + " / " + esc(b.breed || "—") + "</div>" +
            "<div><b>Shed:</b> " + esc(b.shed || "—") + "</div>" +
            "<div><b>Opening:</b> " + esc(b.opening_birds) + " &nbsp; <b>Live:</b> " + esc(b.live_birds) + "</div>" +
            "<div><b>Mortality:</b> " + esc(b.mortality_pct) + "% &nbsp; <b>Avg wt:</b> " + esc(b.avg_weight) + " kg</div>" +
            "<div><b>FCR:</b> " + esc(b.fcr) + " &nbsp; <b>CFCR:</b> " + esc(b.cfcr) + "</div>" +
            "</div>";
        }).join("") +
        (data.last_visit ? '<div class="mt-1"><b>Last visit:</b> ' +
          esc(new Date(data.last_visit).toLocaleDateString()) + "</div>" : "");
      })
      .catch(function () {
        var node = marker.getPopup().getElement();
        var box = node && node.querySelector(".fmp-popup-batch");
        if (box) box.textContent = "Could not load the flock details.";
      });
  }

  function drawRoute() {
    routeLayer.clearLayers();
    if (!plan) return;
    var line = decodeGeometry(plan.geometry);
    if (line && line.length) {
      L.polyline(line, { color: "#1d4ed8", weight: 4, opacity: .8 }).addTo(routeLayer);
      map.fitBounds(L.polyline(line).getBounds(), { padding: [30, 30] });
    }
    // A numbered pin per stop, and the leg distance written on the leg — the
    // "distance labels between stops" the summary panel repeats in words.
    var previous = null;
    plan.stops.forEach(function (stop) {
      if (stop.latitude === null || stop.longitude === null) return;
      L.marker([stop.latitude, stop.longitude], {
        icon: pin(stop.kind === "farm" ? "#2563eb" : "#16a34a", stop.sequence)
      }).bindTooltip(stop.label, { direction: "top" }).addTo(routeLayer);
      // The leg distance written on the leg, halfway along it. The panel says
      // the same numbers, but a distance beside the road it belongs to is the
      // thing somebody actually reads off a map.
      if (previous && stop.leg_distance_km) {
        L.marker([(previous[0] + stop.latitude) / 2,
                  (previous[1] + stop.longitude) / 2], {
          icon: L.divIcon({ className: "", html: '<span class="fmp-leg">' +
                            km(stop.leg_distance_km) + "</span>",
                            iconSize: [0, 0], iconAnchor: [18, 7] }),
          interactive: false
        }).addTo(labelLayer);
      }
      previous = [stop.latitude, stop.longitude];
    });
  }

  function decodeGeometry(geometry) {
    if (!geometry) return null;
    if (geometry.type === "points") return geometry.coordinates;
    if (geometry.type === "geojson") {
      return geometry.coordinates.map(function (c) { return [c[1], c[0]]; });
    }
    if (geometry.type === "polyline" && geometry.encoded) {
      return decodePolyline(geometry.encoded);
    }
    return null;
  }

  // Google's encoded-polyline format, which OSRM also speaks. Small enough to
  // carry here rather than add a dependency for.
  function decodePolyline(str, precision) {
    var index = 0, lat = 0, lng = 0, coordinates = [], shift, result, byte;
    var factor = Math.pow(10, precision === undefined ? 5 : precision);
    while (index < str.length) {
      byte = null; shift = 0; result = 0;
      do { byte = str.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; }
      while (byte >= 0x20);
      lat += ((result & 1) ? ~(result >> 1) : (result >> 1));
      shift = 0; result = 0;
      do { byte = str.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; }
      while (byte >= 0x20);
      lng += ((result & 1) ? ~(result >> 1) : (result >> 1));
      coordinates.push([lat / factor, lng / factor]);
    }
    return coordinates;
  }

  // ---- panels -------------------------------------------------------------

  /* What the search box leaves standing. Name, code and supervisor, because
     those are the three things somebody knows about a farm when they are
     looking for it — and a selected farm is never hidden, or unticking it
     would mean clearing the search first. */
  function pickerRows() {
    var term = (el("fmp-search").value || "").trim().toLowerCase();
    if (!term) return farms;
    return farms.filter(function (f) {
      if (selected.has(f.id)) return true;
      return (f.name + " " + f.code + " " + (f.supervisor || ""))
        .toLowerCase().indexOf(term) !== -1;
    });
  }

  function renderPicker() {
    var box = el("fmp-picker");
    var rows = pickerRows();
    if (!farms.length) {
      box.innerHTML = '<div class="text-muted small p-2">No farms match these filters.</div>';
      return;
    }
    if (!rows.length) {
      box.innerHTML = '<div class="text-muted small p-2">No farm matches that search.</div>';
      return;
    }
    box.innerHTML = rows.map(function (f) {
      return '<label class="d-flex align-items-start gap-2 py-1 px-1">' +
        '<input type="checkbox" class="form-check-input fmp-check" value="' + f.id + '"' +
        (selected.has(f.id) ? " checked" : "") + ">" +
        '<span class="small"><span class="fw-semibold">' + esc(f.name) + "</span>" +
        '<span class="d-block text-muted">' + esc(f.code) + " · " + esc(f.supervisor || "—") + "</span></span>" +
        (f.priority !== "normal"
          ? '<span class="badge ms-auto fmp-badge-' + esc(f.priority) + '">' + esc(f.priority) + "</span>"
          : "") +
        "</label>";
    }).join("");
  }

  function renderSummary() {
    var box = el("fmp-summary");
    if (!plan) {
      box.innerHTML = '<div class="text-muted small p-2">Select farms and choose ' +
        "<strong>Calculate Route</strong>.</div>";
      return;
    }
    var estimate = plan.estimated
      ? '<div class="alert alert-warning py-2 px-2 small mb-2">' +
        "These distances are <b>estimates</b>: the routing service could not be " +
        "reached, so they are straight-line figures with a road allowance, not " +
        "road distances. Do not settle a travel claim on them.</div>"
      : "";
    var notes = (plan.priority_notes || []).length
      ? '<div class="alert alert-info py-2 px-2 small mb-2"><b>Priority route</b><ul class="mb-0 ps-3">' +
        plan.priority_notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") +
        "</ul></div>"
      : "";
    var last = plan.stops[plan.stops.length - 1];
    var head = '<div class="small mb-2">' +
      line("fa-flag", "Start Point", esc(plan.stops[0].label), "text-success") +
      line("fa-flag-checkered", "End Point", esc(last.label), "text-danger") +
      line("fa-tractor", "Total Farms", plan.farm_count) +
      line("fa-road", "Total Distance", km(plan.distance_km)) +
      line("fa-clock", "Estimated Time", hhmm(plan.minutes)) +
      line("fa-route", "Route Mode", esc(modeLabel())) +
      line("fa-satellite-dish", "Measured By",
           esc(plan.basis === "road" ? plan.provider + " (road)" : "straight line")) +
      "</div>";
    var order = '<div class="fw-semibold small mt-2 mb-1">Visit Order (Best Sequence)</div>' +
      plan.stops.map(function (s) {
        return '<div class="fmp-seq ' + (s.kind === "farm" ? "" : "is-" + s.kind) + '">' +
          '<span class="no">' + s.sequence + "</span>" +
          '<span class="nm">' + esc(s.label) +
          (s.kind === "start" ? " (Start)" : s.kind === "end" ? " (End)" : "") + "</span>" +
          '<span class="km">' + (s.leg_distance_km ? km(s.leg_distance_km) : "—") + "</span>" +
          "</div>";
      }).join("");
    box.innerHTML = estimate + notes + head + order;
  }

  function line(icon, label, value, tone) {
    return '<div class="d-flex justify-content-between align-items-center py-1">' +
      '<span class="text-muted"><i class="fas ' + icon + ' me-2"></i>' + label + "</span>" +
      '<b class="' + (tone || "") + '">' + value + "</b></div>";
  }

  function modeLabel() {
    var select = el("f-mode");
    return select.options[select.selectedIndex].textContent.trim();
  }

  function renderTable() {
    var body = el("fmp-body");
    var rows = farms.concat([]);
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="13" class="text-center text-muted py-4">' +
        "No farms match these filters.</td></tr>";
      el("fmp-count").textContent = "";
      el("fmp-pager").innerHTML = "";
      return;
    }
    // With a route in hand the list reads in visiting order, because that is
    // the order the day happens in.
    var seq = {};
    if (plan) {
      plan.stops.forEach(function (s) { if (s.farm_id) seq[s.farm_id] = s.sequence; });
      rows.sort(function (a, b) {
        return (seq[a.id] || 9999) - (seq[b.id] || 9999) || a.name.localeCompare(b.name);
      });
    }

    var pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (page > pages) page = pages;
    var slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    body.innerHTML = slice.map(function (f) {
      var stop = planStopFor(f.id);
      return "<tr>" +
        '<td class="text-center">' +
          (stop ? '<span class="badge bg-primary">' + stop.sequence + "</span>"
                : '<i class="fas fa-house text-muted"></i>') + "</td>" +
        "<td>" + esc(f.code) + "</td><td>" + esc(f.name) + "</td>" +
        "<td>" + esc(f.branch || "—") + "</td><td>" + esc(f.supervisor || "—") + "</td>" +
        "<td>" + esc(f.batch_code || "—") +
          (f.batch_age !== null && f.batch_age !== undefined
            ? '<span class="d-block text-muted small">' + f.batch_age + " days</span>" : "") +
        "</td>" +
        '<td class="ds-num text-end">' + (f.live_birds ? Number(f.live_birds).toLocaleString("en-IN") : "—") + "</td>" +
        '<td class="ds-mid"><span class="badge badge-priority-' + esc(f.priority) + '">' +
          esc(f.priority.charAt(0).toUpperCase() + f.priority.slice(1)) + "</span></td>" +
        '<td class="ds-num text-end">' + (stop ? km(stop.leg_distance_km) : "—") + "</td>" +
        '<td class="ds-num text-end">' + (stop ? km(stop.cumulative_distance_km) : "—") + "</td>" +
        '<td class="ds-num text-end">' + (stop ? hhmm(stop.leg_minutes) : "—") + "</td>" +
        '<td class="ds-mid">' + (f.last_visit
            ? esc(new Date(f.last_visit).toLocaleDateString("en-GB")) : "—") + "</td>" +
        '<td class="ds-mid text-center"><div class="btn-group btn-group-sm">' +
          '<button class="btn btn-outline-secondary fmp-focus" data-farm="' + f.id +
            '" title="Show on map"><i class="fas fa-eye"></i></button>' +
          '<a class="btn btn-outline-secondary" target="_blank" rel="noopener" title="Navigate" href="' +
            "https://www.google.com/maps/dir/?api=1&destination=" + f.latitude + "," + f.longitude +
          '"><i class="fas fa-paper-plane"></i></a>' +
        "</div></td></tr>";
    }).join("");

    var from = (page - 1) * PAGE_SIZE + 1;
    var to = Math.min(page * PAGE_SIZE, rows.length);
    el("fmp-count").textContent = "Showing " + from + " to " + to + " of " +
      rows.length + " farms";
    renderPager(pages);
  }

  function renderPager(pages) {
    var list = el("fmp-pager");
    if (pages < 2) { list.innerHTML = ""; return; }
    var html = '<li class="page-item ' + (page === 1 ? "disabled" : "") +
      '"><a class="page-link fmp-page" data-page="' + (page - 1) + '" href="#">&lsaquo;</a></li>';
    for (var i = 1; i <= pages; i++) {
      html += '<li class="page-item ' + (i === page ? "active" : "") +
        '"><a class="page-link fmp-page" data-page="' + i + '" href="#">' + i + "</a></li>";
    }
    html += '<li class="page-item ' + (page === pages ? "disabled" : "") +
      '"><a class="page-link fmp-page" data-page="' + (page + 1) + '" href="#">&rsaquo;</a></li>';
    list.innerHTML = html;
  }

  function renderMissing() {
    var card = el("fmp-missing-card");
    var body = el("fmp-missing-body");
    // The count rides on the card's own header rather than a summary tile:
    // farms without a pin are an exception to deal with, not a statistic to
    // watch, and the card only appears when there are any.
    var header = card.querySelector(".card-header");
    // A count beside the map as well as the card below it. The card sits under
    // the farm list, which on a phone is a long way from the thing the reader
    // is looking at when they wonder why a farm is not on it.
    var chip = el("fmp-missing-chip");
    var chipCount = el("fmp-missing-count");
    if (chip) chip.classList.toggle("d-none", !missing.length);
    if (chipCount) chipCount.textContent = missing.length;

    if (!missing.length) { card.classList.add("d-none"); return; }
    card.classList.remove("d-none");
    if (header) {
      header.innerHTML = '<i class="fas fa-location-crosshairs"></i> GPS Missing ' +
        '<span class="badge bg-danger ms-1">' + missing.length + "</span>";
    }
    body.innerHTML = missing.map(function (f) {
      return "<tr><td>" + esc(f.code) + "</td><td>" + esc(f.name) + "</td>" +
        "<td>" + esc(f.branch || "—") + "</td><td>" + esc(f.supervisor || "—") + "</td>" +
        '<td class="text-center"><a class="btn btn-sm btn-outline-danger" href="' +
        window.FMP_URLS.capture + '">Capture GPS</a></td></tr>';
    }).join("");
  }

  function renderCounts() {
    el("s-selected").textContent = selected.size;
    el("s-visits").textContent = plan ? plan.farm_count : selected.size;
    el("s-distance").textContent = plan ? km(plan.distance_km) : "—";
    el("s-time").textContent = plan ? hhmm(plan.minutes) : "—";
    el("s-distance-sub").textContent = plan
      ? (plan.estimated ? "straight-line estimate" : "by road")
      : "Planned distance";
    // Distance per stop, which is the figure that says whether a round is a
    // tight morning or a day of driving between three farms.
    el("s-avg").textContent = (plan && plan.farm_count)
      ? km(plan.distance_km / plan.farm_count) : "—";
  }

  function renderAll() {
    renderPicker(); renderSummary(); renderTable(); renderMissing(); renderCounts();
    drawMarkers(); drawRoute();
  }

  /* Where the round starts. The chosen branch's own pin by default — that is
     the head office, and it is what a supervisor's day actually begins from —
     but a start dropped on the map wins, because somebody setting off from
     home is a normal Tuesday and not an exception worth a master record. */
  function branchStart() {
    var id = el("f-branch").value;
    var point = id && window.FMP_BRANCH_POINTS ? window.FMP_BRANCH_POINTS[id] : null;
    if (!point) return null;
    return { label: point.name, latitude: point.latitude, longitude: point.longitude };
  }

  function currentStart() { return startPoint || branchStart(); }

  /* The other way to set the start point — this device's own GPS fix, for a
     supervisor whose day genuinely starts wherever they are standing rather
     than at the branch office or a point picked by eye on the map. */
  function useMyLocation() {
    var button = el("fmp-my-location");
    if (!navigator.geolocation) {
      notify("This browser cannot provide a GPS location. Use “Set on map” instead.", "warning");
      return;
    }
    // Browsers refuse the GPS prompt entirely on a plain http:// origin that
    // is not localhost — e.g. this page opened by IP over the office Wi-Fi
    // (http://192.168.x.x:8000). That refusal looks identical to "permission
    // denied" from getCurrentPosition, so it is caught here first, where it
    // can be named for what it actually is rather than blamed on the user.
    if (!window.isSecureContext) {
      notify("Your device's location can only be shared over a secure (https://) "
        + "connection — this page is open over plain http. Use “Set on map” instead, "
        + "or open this page over https.", "warning");
      return;
    }
    if (pickingStart) { el("fmp-set-start").click(); }
    clearNotice();
    button.disabled = true;
    var original = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Locating…';
    navigator.geolocation.getCurrentPosition(function (position) {
      startPoint = { label: "My Location", source: "gps",
                     latitude: Number(position.coords.latitude.toFixed(6)),
                     longitude: Number(position.coords.longitude.toFixed(6)) };
      plan = null;
      el("fmp-save").disabled = true;
      map.setView([startPoint.latitude, startPoint.longitude], Math.max(map.getZoom(), 12));
      renderStart(); renderSummary(); renderTable(); drawRoute();
      button.disabled = false;
      button.innerHTML = original;
    }, function (error) {
      // POSITION_UNAVAILABLE is what a desktop browser reports when the OS
      // itself has location turned off (Windows Settings > Privacy >
      // Location) — the site permission can be "Allow" and this still fires,
      // so it needs its own message rather than folding into a generic one.
      var message = error.code === error.PERMISSION_DENIED
        ? "Location permission was denied — allow it for this site, or use “Set on map” instead."
        : error.code === error.POSITION_UNAVAILABLE
        ? "This device could not get a location — check that Location is turned on "
          + "in your computer's system settings (Windows: Settings > Privacy & security "
          + "> Location), then try again. Or use “Set on map” instead."
        : "Timed out waiting for a location. Try again, or use “Set on map” instead.";
      notify(message, "warning");
      button.disabled = false;
      button.innerHTML = original;
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  function renderStart() {
    var point = currentStart();
    var label = el("fmp-start-label");
    var hint = el("fmp-start-hint");
    if (point) {
      label.textContent = point.label;
      label.className = "badge bg-dark";
      hint.textContent = !startPoint ? "(branch office)"
        : startPoint.source === "gps" ? "(this device's location)" : "(set on the map)";
    } else {
      label.textContent = "not set";
      label.className = "badge bg-danger";
      hint.textContent = "Choose a branch that has a location, or set one on the map.";
    }
    if (startMarker) { map.removeLayer(startMarker); startMarker = null; }
    if (point) {
      startMarker = L.marker([point.latitude, point.longitude],
                             { icon: pin("#0f172a", "S") })
        .bindTooltip(point.label + " (start)", { direction: "top" }).addTo(map);
    }
  }

  // ---- data ---------------------------------------------------------------

  function filters() {
    return {
      branch: el("f-branch").value,
      supervisor: el("f-supervisor").value,
      farm_status: el("f-status").value,
      batch_status: el("f-batch").value,
      priority: el("f-priority").value
    };
  }

  function load() {
    var query = new URLSearchParams(filters()).toString();
    return fetch(window.FMP_URLS.data + "?" + query, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        farms = data.farms || [];
        missing = data.gps_missing || [];
        el("s-total").textContent = data.counts.total;
        // A farm that has dropped out of the filter cannot stay selected, or a
        // route would be calculated over something nobody can see.
        var visible = new Set(farms.map(function (f) { return f.id; }));
        selected = new Set(Array.from(selected).filter(function (id) { return visible.has(id); }));
        plan = null;
        page = 1;
        el("fmp-save").disabled = true;
        renderAll();
      })
      .catch(function () { notify("Could not load the farms for this map.", "danger"); });
  }

  function calculate() {
    if (!selected.size) {
      notify("Select at least one farm before calculating a route.", "warning");
      return;
    }
    clearNotice();
    var button = el("fmp-calculate");
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Calculating…';
    fetch(window.FMP_URLS.calculate, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(Object.assign({
        farm_ids: Array.from(selected),
        branch: el("f-branch").value,
        mode: el("f-mode").value,
        roundtrip: true
      }, startPoint ? {
        start_label: startPoint.label,
        start_latitude: startPoint.latitude,
        start_longitude: startPoint.longitude
      } : {}))
    }).then(readJson).then(function (result) {
      if (!result.ok) {
        notify(esc(result.data.error || "The route could not be calculated."), "danger");
        return;
      }
      plan = result.data;
      el("fmp-save").disabled = false;
      if (plan.estimated) {
        notify("Routing service unavailable — showing straight-line estimates.", "warning");
      }
      renderAll();
    }).catch(function () {
      notify("The route could not be calculated. Check the network and try again.", "danger");
    }).finally(function () {
      button.disabled = false;
      button.innerHTML = '<i class="fas fa-route"></i> Calculate Route';
    });
  }

  function save() {
    if (!plan) return;
    fetch(window.FMP_URLS.save, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({
        plan: plan,
        branch: el("f-branch").value,
        supervisor: el("f-supervisor").value,
        mode: el("f-mode").value,
        date: window.FMP_TODAY,
        roundtrip: true
      })
    }).then(readJson).then(function (result) {
      if (!result.ok) {
        notify(esc(result.data.error || "The route could not be saved."), "danger");
        return;
      }
      notify("Route <b>" + esc(result.data.route_no) + "</b> saved.", "success");
    }).catch(function () { notify("The route could not be saved.", "danger"); });
  }

  // ---- wiring -------------------------------------------------------------

  function setBase(which) {
    Object.keys(baseLayers).forEach(function (name) {
      if (name === which) { baseLayers[name].addTo(map); }
      else if (map.hasLayer(baseLayers[name])) { map.removeLayer(baseLayers[name]); }
    });
    el("fmp-base-map").className = "btn " + (which === "street" ? "btn-primary" : "btn-outline-secondary");
    el("fmp-base-sat").className = "btn " + (which === "satellite" ? "btn-primary" : "btn-outline-secondary");
  }

  function init() {
    map = L.map("fmp-map").setView([26.43, 82.53], 9);
    baseLayers.street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);
    // Imagery, for judging whether a pin is on the sheds or in the field next
    // to them — which a street map cannot show and a supervisor can.
    baseLayers.satellite = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Imagery &copy; Esri" });
    markerLayer = L.layerGroup().addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    labelLayer = L.layerGroup().addTo(map);

    ["f-branch", "f-supervisor", "f-status", "f-batch", "f-priority"].forEach(function (id) {
      el(id).addEventListener("change", function () {
        if (id === "f-branch") { narrowSupervisors(); startPoint = null; }
        renderStart();
        load();
      });
    });
    el("fmp-my-location").addEventListener("click", useMyLocation);
    el("fmp-set-start").addEventListener("click", function () {
      pickingStart = !pickingStart;
      this.classList.toggle("btn-primary", pickingStart);
      this.classList.toggle("btn-outline-secondary", !pickingStart);
      el("fmp-start-hint").textContent = pickingStart
        ? "Click the map to place the start point."
        : "";
      if (!pickingStart) renderStart();
    });
    map.on("click", function (event) {
      if (!pickingStart) return;
      startPoint = { label: "Start point", source: "map",
                     latitude: Number(event.latlng.lat.toFixed(6)),
                     longitude: Number(event.latlng.lng.toFixed(6)) };
      pickingStart = false;
      var button = el("fmp-set-start");
      button.classList.remove("btn-primary");
      button.classList.add("btn-outline-secondary");
      plan = null;
      el("fmp-save").disabled = true;
      renderStart(); renderSummary(); renderTable(); drawRoute();
    });

    el("fmp-base-map").addEventListener("click", function () { setBase("street"); });
    el("fmp-base-sat").addEventListener("click", function () { setBase("satellite"); });
    el("fmp-show-labels").addEventListener("change", function () {
      if (this.checked) { labelLayer.addTo(map); } else { map.removeLayer(labelLayer); }
    });
    el("fmp-fullscreen").addEventListener("click", function () {
      var node = el("fmp-map");
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else if (node.requestFullscreen) {
        node.requestFullscreen();
      }
      // Leaflet sizes itself to its container, and the container has just
      // changed size under it.
      window.setTimeout(function () { map.invalidateSize(); }, 300);
    });

    el("fmp-refresh").addEventListener("click", load);
    el("fmp-calculate").addEventListener("click", calculate);
    el("fmp-save").addEventListener("click", save);
    el("fmp-search").addEventListener("input", renderPicker);
    // "All" means all of what the search has left showing, which is what a
    // filtered list implies — otherwise searching would be a lie the moment
    // somebody pressed it.
    el("fmp-all").addEventListener("click", function () {
      pickerRows().forEach(function (f) { selected.add(f.id); });
      plan = null; page = 1; renderAll();
    });
    el("fmp-none").addEventListener("click", function () {
      selected.clear(); plan = null; renderAll();
    });

    document.addEventListener("change", function (event) {
      if (!event.target.classList.contains("fmp-check")) return;
      var id = Number(event.target.value);
      if (event.target.checked) selected.add(id); else selected.delete(id);
      plan = null;
      el("fmp-save").disabled = true;
      renderCounts(); drawMarkers(); drawRoute(); renderSummary(); renderTable();
    });

    document.addEventListener("click", function (event) {
      var pick = event.target.closest(".fmp-pick");
      if (pick) {
        var id = Number(pick.dataset.farm);
        if (selected.has(id)) selected.delete(id); else selected.add(id);
        plan = null; renderAll();
        return;
      }
      var pager = event.target.closest(".fmp-page");
      if (pager) {
        event.preventDefault();
        var wanted = Number(pager.dataset.page);
        if (wanted >= 1) { page = wanted; renderTable(); }
        return;
      }
      var focus = event.target.closest(".fmp-focus");
      if (focus) {
        var farm = farms.filter(function (f) { return f.id === Number(focus.dataset.farm); })[0];
        if (farm) map.setView([farm.latitude, farm.longitude], 14);
      }
    });

    narrowSupervisors();
    renderStart();
    load();
  }

  /* Branch → Supervisor, the ERP's own hierarchy: choosing a branch must not
     leave another branch's supervisors on offer. */
  function narrowSupervisors() {
    var branch = el("f-branch").value;
    var select = el("f-supervisor");
    Array.prototype.forEach.call(select.options, function (option) {
      if (!option.value) return;
      var mine = !branch || option.dataset.branch === branch;
      option.hidden = !mine;
      option.disabled = !mine;
      if (!mine && select.value === option.value) select.value = "";
    });
  }

  return { init: init };
})();
