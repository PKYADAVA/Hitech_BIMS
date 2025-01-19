$(document).ready(function() {
    // Initialize DataTable
    const table = $('#attendanceTable').DataTable({
        responsive: true,
        order: [[3, 'desc'], [5, 'desc']],
        pageLength: 25,
        dom: '<"d-flex justify-content-between align-items-center mb-3"Bf>rtip',
        buttons: [
            {
                extend: 'excel',
                text: '<i class="fas fa-file-excel me-2"></i>Export Excel',
                className: 'btn btn-success',
                exportOptions: {
                    columns: [0, 1, 2, 3, 4, 5, 6, 7]
                },
                filename: () => `Attendance_Report_${new Date().toISOString().split('T')[0]}`
            }
        ],
        language: {
            search: "",
            searchPlaceholder: "Search records..."
        }
    });

    // Set default date to today
    $('#date').val(new Date().toISOString().split('T')[0]);

    // Handle status change
    $('#status').change(function() {
        const status = $(this).val();
        const timeInputs = $('#check_in, #check_out');
        
        if (status === 'Absent' || status === 'On Leave') {
            timeInputs.val('').prop('disabled', true);
        } else {
            timeInputs.prop('disabled', false);
        }
    });

    // Save attendance
    $('#saveAttendance').click(function() {
        const formData = new FormData($('#attendanceForm')[0]);
        const attendanceId = $('#attendance_id').val();
        
        // Create data object
        const data = {
            employee_id: formData.get('employee'),
            date: formData.get('date'),
            check_in_time: formData.get('check_in'),
            check_out_time: formData.get('check_out'),
            status: formData.get('status'),
            remarks: formData.get('remarks')
        };

        if (attendanceId) {
            data.id = attendanceId;
        }

        // Validate required fields
        if (!data.employee_id || !data.date || !data.status) {
            Swal.fire({
                icon: 'error',
                title: 'Validation Error',
                text: 'Please fill in all required fields.'
            });
            return;
        }

        $.ajax({
            url: `/attendance/`,
            type: attendanceId ? 'PUT':'POST',
            data: JSON.stringify(data),
            contentType: 'application/json',
            headers: {
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            },
            success: function(response) {
                Swal.fire({
                    icon: 'success',
                    title: 'Success',
                    text: response.message,
                    showConfirmButton: false,
                    timer: 1500
                }).then(() => location.reload());
            },
            error: function(xhr) {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: xhr.responseText || 'Failed to save attendance. Please try again.'
                });
            }
        });
    });

    // Edit attendance
    $(document).on('click', '.edit-attendance', function () {
        const attendanceId = $(this).data('id');
        
        // Fetch attendance details
        $.get(`/attendance/?id=${attendanceId}`, function (data) {
            $('#editattendance_id').val(data.id);
            $('#editemployee').val(data.employee_id);
            $('#editdate').val(data.date);
            $('#editcheck_in').val(data.check_in_time);
            $('#editcheck_out').val(data.check_out_time);
            $('#editstatus').val(data.status).trigger('change');
            //$('#editremarks').val(data.remarks);
            
            $('#EditmodalTitle').text('Edit Attendance');
            $('#attendanceEditModal').modal('show');
        });
    });
    
    // Reset modal on close
    $('#attendanceEditModal').on('hidden.bs.modal', function () {
        $('#EditattendanceForm')[0].reset();
        $('#editattendance_id').val('');
        $('#EditmodalTitle').text('Mark Attendance');
    });
    
    // Save attendance (PUT request)
    $('#EditAttendance').on('click', function () {
        const formData = new FormData($('#EditattendanceForm')[0]);
        const attendanceData = {
            id: $('#editattendance_id').val(),
            date: $('#editdate').val(),
            check_in_time: $('#editcheck_in').val(),
            check_out_time: $('#editcheck_out').val(),
            status: $('#editstatus').val(),
            remarks: $('#editremarks').val(),
        };
    
        $.ajax({
            url: `/attendance/`,
            type: 'PUT',
            contentType: 'application/json',
            headers: {
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            },
            data: JSON.stringify(attendanceData),
            success: function (response) {
                Swal.fire({
                    icon: 'success',
                    title: 'Success',
                    text: response.message,
                    showConfirmButton: false,
                    timer: 1500
                }).then(() => location.reload());
            },
            error: function (xhr) {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: xhr.responseText || 'Failed to update attendance. Please try again.'
                });
            }
        });
    });
    
    // Reset form on modal close
    $('#attendanceModal').on('hidden.bs.modal', function() {
        $('#attendanceForm')[0].reset();
        $('#attendance_id').val('');
        $('#modalTitle').text('Mark Attendance');
        $('#status').trigger('change');
        $('#date').val(new Date().toISOString().split('T')[0]);
    });

    // Form validation before submit
    $('#attendanceForm').on('submit', function(e) {
        e.preventDefault();
        $('#saveAttendance').click();
    });

    // Delete attendance
    $(document).on('click', '.delete-attendance', function () {
        const attendanceId = $(this).data('id');
        console.log(attendanceId)
        if (confirm('Are you sure you want to delete this attendance record?')) {
            
            $.ajax({
                url: `/attendance/?id=${attendanceId}`,  // Adjust the URL as per your Django endpoint
                type: 'DELETE',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),  // Ensure CSRF token is included
                },
                success: function (response) {
                    $(`#attendance-row-${attendanceId}`).remove();
                    Swal.fire({
                        icon: 'success',
                        title: 'Success',
                        text: response.message,
                        showConfirmButton: false,
                        timer: 1500
                    }).then(() => location.reload());
                },
                error: function (xhr) {
                    Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: xhr.responseText || 'Failed to delete attendance. Please try again.'
                    });
                }
            });
        }
    });
    // Function to get CSRF token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                // Does this cookie string begin with the name we want?
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});