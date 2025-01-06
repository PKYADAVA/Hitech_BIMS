$(document).ready(function () {
    $('#example').DataTable();

    // Initialize all dropdowns
    $('.dropdown-toggle').each(function () {
        new bootstrap.Dropdown(this);
    });
});