$(document).ready(function(){
    // Add employee modal
    $('#addEmployeeModal').on('show.bs.modal', function (event) {
        var button = $(event.relatedTarget);
        var modal = $(this);
        modal.find('#addEmployeeForm').trigger('reset');
    });

    function getBadgeClass(status) {
        switch(status) {
            case 'Present': return 'bg-success';
            case 'Absent': return 'bg-danger';
            case 'On Leave': return 'bg-warning text-dark';
            case 'First Half': return 'bg-info';
            case 'Second Half': return 'bg-secondary';
            default: return '';
        }
    }

    // Edit employee modal
    function onloademplyeelist() {
        $.ajax({
            url: '/attendance/',
            type: 'GET',
            success: function(response){
                // Get the table body where rows will be added
                let tableBody = $('#attendance-table-body');
                let dataTable = $('#attendanceTable').DataTable();

                // Clear current table content
                tableBody.empty();
                
                // Loop through each attendance item in the response
                response.attendances.forEach(function(attendance) {
                    let row = `<tr data-id="${attendance.id}">
                                <td>${attendance.employee__employee_id}</td>
                                <td>${attendance.employee__full_name}</td>
                                <td>${attendance.employee__designation__title || '-'}</td>
                                <td>${new Date(attendance.date).toLocaleDateString("en-GB")}</td>
                                <td>
                                    <span class="badge ${getBadgeClass(attendance.status)}">
                                        ${attendance.status}
                                    </span>
                                </td>
                                <td>
                                    <button class="btn btn-sm btn-primary edit-attendance" data-id="${attendance.id}" title="Edit Attendance">
                                        <i class="fas fa-edit"></i>
                                    </button>
                                    <button class="btn btn-sm btn-danger delete-attendance" data-id="${attendance.id}" title="Delete Attendance">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </td>
                            </tr>`;
                    tableBody.append(row);
                });
                
                // Redraw the table without reinitializing it
                dataTable.clear().rows.add($(tableBody).find('tr')).draw();
            },
            error: function(error){
                console.error(error);
            }
        });
    }

    $(document).on('click', '.edit-attendance', function() {
        var attendanceId = $(this).data('id');

        // Make an AJAX GET request to fetch the attendance details using the attendance ID
        $.ajax({
            url: `/attendance/${attendanceId}/`,
            type: 'GET',
            success: function(response) {
                $('#attendanceEditModal').remove();
                
                const modalHTML = `
                <div class="modal fade" id="attendanceEditModal" tabindex="-1">
                    <div class="modal-dialog modal-lg">
                        <div class="modal-content">
                            <div class="modal-header bg-primary text-white">
                                <h5 class="modal-title">
                                    <i class="fas fa-user-clock me-2"></i>
                                    <span id="EditmodalTitle">Edit Attendance</span>
                                </h5>
                                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                            </div>
                            <div class="modal-body">
                                <form id="EditattendanceForm">
                                    <input type="hidden" id="editattendance_id" name="attendance_id" value="${response.id}">
                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="mb-3">
                                                <label for="employee" class="form-label required">Employee</label>
                                                <select class="form-select" id="editemployee" name="employee" required>
                                                    <option value="">Select Employee</option>
                                                    <option value="${response.employee_id}" selected>
                                                        ${response.employee_id} - ${response.employee_name}
                                                    </option>
                                                </select>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div class="mb-3">
                                                <label for="date" class="form-label required">Date</label>
                                                <input type="date" class="form-control" id="editdate" name="date" 
                                                    value="${new Date(response.date).toISOString().split('T')[0]}" required>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="mb-3">
                                                <label for="check_in" class="form-label">Check In Time</label>
                                                <input type="time" class="form-control" id="editcheck_in" name="check_in" 
                                                    value="${response.check_in_time || ''}">
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div class="mb-3">
                                                <label for="check_out" class="form-label">Check Out Time</label>
                                                <input type="time" class="form-control" id="editcheck_out" name="check_out" 
                                                    value="${response.check_out_time || ''}">
                                            </div>
                                        </div>
                                    </div>
                                    <div class="row">
                                        <div class="col-md-6">
                                            <div class="mb-3">
                                                <label for="status" class="form-label required">Status</label>
                                                <select class="form-select" id="editstatus" name="status" required>
                                                    <option value="Present" ${response.status === 'Present' ? 'selected' : ''}>Present</option>
                                                    <option value="Absent" ${response.status === 'Absent' ? 'selected' : ''}>Absent</option>
                                                    <option value="On Leave" ${response.status === 'On Leave' ? 'selected' : ''}>On Leave</option>
                                                    <option value="First Half" ${response.status === 'First Half' ? 'selected' : ''}>First Half</option>
                                                    <option value="Second Half" ${response.status === 'Second Half' ? 'selected' : ''}>Second Half</option>
                                                </select>
                                            </div>
                                        </div>
                                    </div>
                                </form>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                    <i class="fas fa-times me-2"></i>Cancel
                                </button>
                                <button type="button" class="btn btn-primary" id="EditAttendance">
                                    <i class="fas fa-save me-2"></i>Update
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            
                $('body').append(modalHTML);
            
                $('#editattendance_id').val(response.id);
                $('#editemployee').val(response.employee_id);
                $('#editdate').val(new Date(response.date).toISOString().split('T')[0]);
                $('#editcheck_in').val(response.check_in_time || '');
                $('#editcheck_out').val(response.check_out_time || '');
                $('#editstatus').val(response.status);
            
                $('#attendanceEditModal').modal('show');
            },               
            error: function(error) {
                console.error(error);
            }
        });
    });

    $(document).on('click', '#EditAttendance', function() {
        var attendanceId = $('#editattendance_id').val();
        var employeeId = $('#editemployee').val();
        var date = $('#editdate').val();
        var checkIn = $('#editcheck_in').val();
        var checkOut = $('#editcheck_out').val();
        var status = $('#editstatus').val();
        
        var data = {
            attendance_id: attendanceId,
            employee_id: employeeId,
            date: date,
            check_in_time: checkIn,
            check_out_time: checkOut,
            status: status
        };
        
        $.ajax({
            url: `/attendance/${attendanceId}/`,
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify(data),
            success: function(response) {
                onloademplyeelist();
                $('#attendanceEditModal').modal('hide');
            
            },
            error: function(error) {
                console.error('Error updating attendance:', error);
            }
        });
    });
    
    $(document).on('click', '.delete-attendance', function() {
        var attendanceId = $(this).data('id');
        
        if (confirm('Are you sure you want to delete this attendance record?')) {
            $.ajax({
                url: `/attendance/${attendanceId}/`,
                type: 'DELETE',
                success: function(response) {
                    onloademplyeelist();  // Refresh the table without reinitializing
                },
                error: function(error) {
                    console.error('Error deleting attendance:', error);
                    alert('Failed to delete attendance.');
                }
            });
        }
    });

    $(document).on('click', '#saveAttendance', function() {
        // Gather form data
        var attendanceId = $('#attendance_id').val();
        var employeeId = $('#employee').val();
        var date = $('#date').val();
        var checkIn = $('#check_in').val();
        var checkOut = $('#check_out').val();
        var status = $('#status').val();

        $('#attendance_id').val('');
        $('#employee').val('');
        $('#date').val('');
        $('#check_in').val('');
        $('#check_out').val('');
    
        var data = {
            attendance_id: attendanceId,
            employee_id: employeeId,
            date: date,
            check_in_time: checkIn,
            check_out_time: checkOut,
            status: status
        };
    
        // Make the POST request to save attendance
        $.ajax({
            url: '/attendance/',
            type: 'POST',
            data: JSON.stringify(data),
            success: function(response) {
                onloademplyeelist();
                $('#attendanceModal').modal('hide');
            },
            error: function(error) {
                console.error('Error saving attendance:', error);
                alert('Failed to save attendance.');
            }
        });
    });
    $("#fromDate, #toDate").change(function() {
        console.log("called")
        // Get the selected 'from' and 'to' dates
        const fromDate = $("#fromDate").val();
        const toDate = $("#toDate").val();

        // Check if both dates are selected
        if (fromDate && toDate) {
            // Create the payload with the selected dates
            const payload = {
                from_date: fromDate,
                to_date: toDate
            };

            $.ajax({
                url: "/attendance/",
                method: "GET",
                data: payload,
                success: function(response) {
                    console.log("Data received:", response);
                    // Get the table body where rows will be added
                    let tableBody = $('#attendance-table-body');
                    let dataTable = $('#attendanceTable').DataTable();

                    // Clear current table content
                    tableBody.empty();
                    
                    // Loop through each attendance item in the response
                    response.attendances.forEach(function(attendance) {
                        let row = `<tr data-id="${attendance.id}">
                                    <td>${attendance.employee__employee_id}</td>
                                    <td>${attendance.employee__full_name}</td>
                                    <td>${attendance.employee__designation__title || '-'}</td>
                                    <td>${new Date(attendance.date).toLocaleDateString("en-GB")}</td>
                                    <td>
                                        <span class="badge ${getBadgeClass(attendance.status)}">
                                            ${attendance.status}
                                        </span>
                                    </td>
                                    <td>
                                        <button class="btn btn-sm btn-primary edit-attendance" data-id="${attendance.id}" title="Edit Attendance">
                                            <i class="fas fa-edit"></i>
                                        </button>
                                        <button class="btn btn-sm btn-danger delete-attendance" data-id="${attendance.id}" title="Delete Attendance">
                                            <i class="fas fa-trash"></i>
                                        </button>
                                    </td>
                                </tr>`;
                        tableBody.append(row);
                    });
                
                    // Redraw the table without reinitializing it
                    dataTable.clear().rows.add($(tableBody).find('tr')).draw();
                },
                error: function(xhr, status, error) {
                    console.log("Error:", error);
                }
            });
        } else {
            console.log("Please select both dates.");
        }
    });
    
    onloademplyeelist();
});
