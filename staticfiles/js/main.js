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
