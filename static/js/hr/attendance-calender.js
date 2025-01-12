$(document).ready(function() {
    $('#employee_details').change(function() {
        var selectedOption = $(this).find('option:selected');
        var employeeId = selectedOption.data('id');
        console.log(employeeId);

        if (employeeId) {
            $('.card.mb-4').removeClass('d-none');
            
            $('#selected-employee').empty();

            $('#selected-employee').append('<option value="' + employeeId + '" disabled selected>' + employeeId + '</option>');
        } else {
            $('.card.mb-4').addClass('d-none');
        }
    });
});
