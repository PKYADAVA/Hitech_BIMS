$(document).ready(function () {
    // Initialize DataTable
    $('#example').DataTable();
    $('.dropdown-toggle').each(function () {
        new bootstrap.Dropdown(this);
    });

    $('.dropdown-submenu > a').on('click', function (e) {
      var $subMenu = $(this).next('.dropdown-menu');
  
      $subMenu.toggleClass('show');
  
      e.stopPropagation();
      e.preventDefault();
    });
  
    $(document).on('click', function (e) {
      if (!$(e.target).closest('.dropdown').length) {
        $('.dropdown-menu').removeClass('show');
      }
    });
  
    $('.dropdown-submenu > a').on('click', function () {
      var $currentMenu = $(this).next('.dropdown-menu');
      $('.dropdown-submenu .dropdown-menu').not($currentMenu).removeClass('show');
    });

    $(document).on('click', function (e) {
      if (!$(e.target).closest('.dropdown-attendance').length) {
        $('.dropdown-attendance-menu').removeClass('show');
      }
    });

    $('.dropdown-attendance-menu > a').on('click', function (e) {
      var currentMenu = $(this).closest('.dropdown-attendance-menu');
      $('.dropdown-attendance-menu').not(currentMenu).removeClass('show');
    });
  });      
