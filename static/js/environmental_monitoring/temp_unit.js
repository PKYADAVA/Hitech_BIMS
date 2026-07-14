/**
 * Shared Celsius/Fahrenheit display toggle for Environmental Monitoring pages.
 *
 * Storage stays Celsius everywhere (models, thresholds, calibration) - this
 * only controls how temperatures are *displayed*. The chosen unit persists
 * in localStorage so it's consistent across every page in this module.
 */
const EnvTempUnit = (function () {
  const STORAGE_KEY = "envMonitoringTempUnit";

  function get() {
    return localStorage.getItem(STORAGE_KEY) || "C";
  }

  function set(unit) {
    localStorage.setItem(STORAGE_KEY, unit);
  }

  function toDisplayValue(celsius) {
    const value = parseFloat(celsius);
    if (celsius === null || celsius === undefined || celsius === "" || Number.isNaN(value)) {
      return null;
    }
    return get() === "F" ? (value * 9 / 5 + 32) : value;
  }

  function format(celsius) {
    const value = toDisplayValue(celsius);
    if (value === null) return "—";
    return value.toFixed(1) + (get() === "F" ? "°F" : "°C");
  }

  function unitLabel() {
    return get() === "F" ? "°F" : "°C";
  }

  /** Wires up a toggle's radio inputs (name="tempUnit", values "C"/"F") and
   * calls onChange(unit) whenever the user switches, so callers can re-render. */
  function initToggle(toggleSelector, onChange) {
    const container = document.querySelector(toggleSelector);
    if (!container) return;
    const radios = container.querySelectorAll('input[name="tempUnit"]');
    const current = get();
    radios.forEach(function (radio) {
      radio.checked = radio.value === current;
      radio.addEventListener("change", function () {
        if (this.checked) {
          set(this.value);
          if (onChange) onChange(this.value);
        }
      });
    });
  }

  return { get, set, format, toDisplayValue, unitLabel, initToggle };
})();
