$(document).ready(function () {
    $('#employeeTable').DataTable({
        // Optional configurations
        paging: true,       // Enable pagination
        searching: true,    // Enable search
        ordering: true,     // Enable column sorting
        columnDefs: [
            { orderable: false, targets: -1 }, // Disable sorting on the "Action" column
        ],
        lengthMenu: [5, 10, 25, 50], // Page size options
        language: {
            search: "Search Employees:", // Customize search label
        },
    });
    $(document).on('click', '.relieveEmployee', function () {
        const buttonId = $(this).attr('id');
        const Employeeid = buttonId.split('-')[1];
    
        $('#confirmationRelieveMessage').text('Are you sure you want to relieve this employee?').removeClass('text-success text-danger');
        $('#relieveConfirmationModal').modal('show');
    
        $('#confirmRelieveButton').off('click').click(function () {
            if (!Employeeid) return;
    
            $.ajax({
                url: `/employees/${Employeeid}/relieve/`,
                type: 'GET',
                success: function (response) {
                    if (response.success) {
                        $('#confirmationRelieveMessage')
                            .text(response.message)
                            .addClass('text-success')
                            .removeClass('text-danger');
            
                        setTimeout(() => {
                            $('#relieveConfirmationModal').modal('hide');
            
                            // Update the button to show "Relieved" and disable it
                            $(`#relieveEmployee-${response.employee_id}`)
                                .replaceWith('<button class="btn btn-outline-secondary btn-sm" disabled>Relieved</button>');
            
                            // Update the "relieve" status cell dynamically
                            const statusCell = $(`#statusCell-${response.employee_id}`);
                            if (response.relieve_status) {
                                statusCell
                                    .text('Yes')
                                    .css({
                                        backgroundColor: '#874848',
                                        color: '#fff',
                                    });
                            } else {
                                statusCell
                                    .text('No')
                                    .css({
                                        backgroundColor: '#609160',
                                        color: '#fff',
                                    });
                            }
                        }, 2000);
                    } else {
                        $('#confirmationRelieveMessage')
                            .text('Failed to relieve employee: ' + response.message)
                            .addClass('text-danger')
                            .removeClass('text-success');
                    }
                },
                error: function (xhr) {
                    $('#confirmationRelieveMessage')
                        .text('Error relieving employee: ' + xhr.responseText)
                        .addClass('text-danger')
                        .removeClass('text-success');
                },
            });
            
        });
    });
    
    
    $(document).on('click', '.delete-btn', function () {
        const buttonId = $(this).attr('id');
        const Employeeid = buttonId.split('-')[1];
    
        $('#confirmationMessage').text('Are you sure you want to delete this employee?').removeClass('text-success text-danger');
        $('#deleteConfirmationModal').modal('show');
    
        $('#confirmDeleteButton').off('click').click(function () {
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
                            $(`#deleteEmployee-${response.employee_id}`).closest('tr').remove();
                        }, 2000);
                    } else {
                        $('#confirmationMessage')
                            .text('Failed to delete employee: ' + response.message)
                            .addClass('text-danger')
                            .removeClass('text-success');
                    }
                },
                error: function (xhr) {
                    $('#confirmationMessage')
                        .text('Error deleting employee: ' + xhr.responseText)
                        .addClass('text-danger')
                        .removeClass('text-success');
                },
            });
        });
    });
    
});