$(document).ready(function () {
    $(document).on('click', '.delete-btn', function () {
        const buttonId = $(this).attr('id');
        const Employeeid = buttonId.split('-')[1]

        $('#confirmationMessage').text('Are you sure you want to delete this employee?').removeClass('text-success text-danger');

        $('#deleteConfirmationModal').modal('show');

        $('#confirmDeleteButton').click(function () {
            if (!Employeeid) return;

            $.ajax({
                url: `/employees/${Employeeid}/delete/`,
                type: 'GET',
                success: function (response) {
                    if (response.success) {
                        $('#confirmationMessage')
                            .text('Employee deleted successfully!')
                            .addClass('text-success')
                            .removeClass('text-danger');
                        setTimeout(() => {
                            $('#deleteConfirmationModal').modal('hide');
                            $(`#deleteEmployee-${Employeeid}`).closest('tr').remove();
                        }, 2000);
                    } else {
                        $('#confirmationMessage')
                            .text('Failed to delete employee: ' + response.message)
                            .addClass('text-danger')
                            .removeClass('text-success');
                    }
                },
                error: function (xhr, status, error) {
                    $('#confirmationMessage')
                        .text('Error deleting employee: ' + xhr.responseText)
                        .addClass('text-danger')
                        .removeClass('text-success');
                },
            });
        });
    });
});