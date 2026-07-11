// Applied to every DataTable on the site as soon as this script runs (i.e.
// before any page's own $(document).ready() handler calls .DataTable()),
// since defaults must be set before initialization, not inside a ready
// callback of our own - ready handlers fire in registration order, and
// individual pages register theirs earlier in the document than this file.
$.extend(true, $.fn.dataTable.defaults, {
  dom: "Blfrtip",
  buttons: [
    { extend: "copyHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "csvHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "excelHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "pdfHtml5", exportOptions: { columns: "th:not(:last-child)" }, orientation: "landscape" },
    { extend: "print", exportOptions: { columns: "th:not(:last-child)" } },
    "colvis",
  ],
});

$(document).ready(function () {
  $('#example').DataTable();

  $('.dropdown-toggle').each(function () {
    new bootstrap.Dropdown(this);
  });

  $('.dropdown-submenu').on('mouseenter', function () {
    $(this).find('.dropdown-menu').addClass('show');
  });

  $('.dropdown-submenu').on('mouseleave', function () {
    $(this).find('.dropdown-menu').removeClass('show');
  });

  $(document).on('click', function (e) {
    if (!$(e.target).closest('.dropdown').length) {
      $('.dropdown-menu').removeClass('show');
    }
  });
});
