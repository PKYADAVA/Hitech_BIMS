/* Route History — a saved round, and the journey it was driven as.
 *
 * The map here redraws a stored geometry rather than asking a provider again:
 * a route that has already been calculated has already been paid for, and its
 * kilometres must not change under a report because a road was resurfaced
 * since. Recalculating is a deliberate act, not something a View button does.
 */
window.RouteHistory = (function () {
  "use strict";

  var map = null, layer = null, modal = null;

  function el(id) { return document.getElementById(id); }

  function esc(text) {
    if (window.escapeHtml) return window.escapeHtml(text);
    var d = document.createElement("div");
    d.textContent = text === null || text === undefined ? "" : String(text);
    return d.innerHTML;
  }

  function csrf() {
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function url(template, id) { return template.replace(/\/0\//, "/" + id + "/"); }

  function readJson(response) {
    return response.text().then(function (body) {
      try { return { ok: response.ok, data: JSON.parse(body) }; }
      catch (err) {
        return { ok: false, data: { error: "The server returned an unexpected response (" +
                 response.status + ")." } };
      }
    });
  }

  function notify(message, tone) {
    var box = el("rh-alert");
    box.className = "alert alert-" + (tone || "info");
    box.innerHTML = message;
    box.classList.remove("d-none");
  }

  function decodePolyline(str) {
    var index = 0, lat = 0, lng = 0, out = [], shift, result, byte;
    while (index < str.length) {
      byte = null; shift = 0; result = 0;
      do { byte = str.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; }
      while (byte >= 0x20);
      lat += ((result & 1) ? ~(result >> 1) : (result >> 1));
      shift = 0; result = 0;
      do { byte = str.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; }
      while (byte >= 0x20);
      lng += ((result & 1) ? ~(result >> 1) : (result >> 1));
      out.push([lat / 1e5, lng / 1e5]);
    }
    return out;
  }

  function geometryPoints(geometry) {
    if (!geometry) return null;
    if (geometry.type === "points") return geometry.coordinates;
    if (geometry.type === "geojson") {
      return geometry.coordinates.map(function (c) { return [c[1], c[0]]; });
    }
    if (geometry.type === "polyline" && geometry.encoded) return decodePolyline(geometry.encoded);
    return null;
  }

  function pin(colour, label) {
    return L.divIcon({
      className: "",
      html: '<div style="background:' + colour + ';width:1.3rem;height:1.3rem;' +
            "border-radius:50%;border:2px solid #fff;color:#fff;font-size:.68rem;" +
            'display:flex;align-items:center;justify-content:center;">' + label + "</div>",
      iconSize: [21, 21], iconAnchor: [10, 10]
    });
  }

  function renderDeviation(d) {
    if (!d.trip_no) {
      return '<div class="alert alert-secondary py-2 px-2 small mb-2">' +
        "This round has not been started as a trip, so there is nothing to " +
        "compare it against yet.</div>";
    }
    var head = d.sequence_changed
      ? '<div class="alert alert-warning py-2 px-2 small mb-2"><b>Route deviation</b> — ' +
        "the farms were not reached in the planned order.</div>"
      : '<div class="alert alert-success py-2 px-2 small mb-2">Driven in the planned order.</div>';
    var rows = "" +
      row("Trip", esc(d.trip_no)) +
      row("Farms planned / visited", d.planned_farms + " / " + d.visited_farms) +
      row("Planned distance", d.planned_distance_km + " km") +
      (d.actual_distance_known
        ? row("Actual distance", d.actual_distance_km + " km") +
          row("Extra distance", d.extra_distance_km + " km") +
          row("Route efficiency", d.efficiency_pct + "%")
        : '<div class="small text-muted mt-1">No odometer reading on the trip yet, ' +
          "so the actual distance is not known. It is not a zero-kilometre day.</div>");
    var missed = d.missed_farms.length
      ? '<div class="small text-danger mt-1"><b>Not visited:</b> ' +
        d.missed_farms.map(esc).join(", ") + "</div>"
      : "";
    var order = d.out_of_turn.length
      ? '<div class="small mt-1"><b>Out of turn:</b><ul class="mb-0 ps-3">' +
        d.out_of_turn.map(function (o) {
          return "<li>" + esc(o.farm) + " — planned " + o.planned + ", reached " + o.actual + "</li>";
        }).join("") + "</ul></div>"
      : "";
    return head + '<div class="small">' + rows + "</div>" + missed + order;
  }

  function row(label, value) {
    return "<div class='d-flex justify-content-between'><span class='text-muted'>" +
      label + "</span><b>" + value + "</b></div>";
  }

  function show(routeId) {
    fetch(url(window.RH_URLS.detail, routeId), { credentials: "same-origin" })
      .then(readJson)
      .then(function (result) {
        if (!result.ok) { notify(esc(result.data.error || "Could not load the route."), "danger"); return; }
        var data = result.data;
        el("rh-title").textContent = data.route.route_no +
          " · " + data.route.date + " · " + (data.route.supervisor || "no supervisor");
        el("rh-alert").classList.add("d-none");
        el("rh-deviation").innerHTML = renderDeviation(data.deviation);
        el("rh-stops").innerHTML = data.stops.map(function (s) {
          var off = s.actual_sequence && s.actual_sequence !== s.sequence;
          return '<div class="rh-seq ' + (off ? "off" : "") + '">' +
            '<span class="no">' + s.sequence + "</span><span>" +
            '<span class="fw-medium">' + esc(s.label) + "</span>" +
            '<span class="mt d-block">' + s.leg_distance_km + " km · cum " +
            s.cumulative_distance_km + " km" +
            (s.visited_at ? " · reached " + new Date(s.visited_at).toLocaleTimeString() : "") +
            (off ? " · <b class='text-warning-emphasis'>out of turn</b>" : "") +
            "</span></span></div>";
        }).join("");

        modal.show();
        // Leaflet needs a visible container to size itself, so the map is
        // built after the modal is on screen rather than behind it.
        window.setTimeout(function () { drawMap(data); }, 250);
      })
      .catch(function () { notify("Could not load the route.", "danger"); });
  }

  function drawMap(data) {
    if (!map) {
      map = L.map("rh-map").setView([26.43, 82.53], 9);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(map);
      layer = L.layerGroup().addTo(map);
    }
    map.invalidateSize();
    layer.clearLayers();
    var line = geometryPoints(data.route.geometry);
    var bounds = [];
    if (line && line.length) {
      L.polyline(line, { color: "#1d4ed8", weight: 4, opacity: .8 }).addTo(layer);
      bounds = line;
    }
    data.stops.forEach(function (s) {
      if (s.latitude === null || s.longitude === null) return;
      L.marker([s.latitude, s.longitude], {
        icon: pin(s.visited_at ? "#16a34a" : (s.kind === "farm" ? "#1d4ed8" : "#0f172a"),
                  s.sequence)
      }).bindTooltip(s.label, { direction: "top" }).addTo(layer);
      bounds.push([s.latitude, s.longitude]);
    });
    if (bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [25, 25] });
  }

  function startTrip(routeId, button) {
    button.disabled = true;
    fetch(url(window.RH_URLS.startTrip, routeId), {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: "{}"
    }).then(readJson).then(function (result) {
      if (!result.ok) {
        window.alert(result.data.error || "The trip could not be created.");
        button.disabled = false;
        return;
      }
      window.location.reload();
    }).catch(function () {
      window.alert("The trip could not be created.");
      button.disabled = false;
    });
  }

  function init() {
    modal = new bootstrap.Modal(document.getElementById("rhModal"));
    document.addEventListener("click", function (event) {
      var view = event.target.closest(".rh-view");
      if (view) { show(view.dataset.route); return; }
      var start = event.target.closest(".rh-start");
      if (start) { startTrip(start.dataset.route, start); }
    });
  }

  return { init: init };
})();
