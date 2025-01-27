$(document).ready(function () {
    // CSRF token setup for AJAX
    function getCSRFToken() {
        return $("input[name=csrfmiddlewaretoken]").val();
    }

    // Function to load farms data into the table
    function loadFarms() {
        $.ajax({
            url: "/broiler_farm/",
            type: "GET",
            success: function (data) {
                const table = $("#farm-table");
    
                // Destroy existing DataTable instance if it exists
                if ($.fn.DataTable.isDataTable(table)) {
                    console.log("Destroying existing DataTable instance...");
                    table.DataTable().clear().destroy();
                }
    
                // Clear and repopulate the table
                const tbody = table.find("tbody");
                tbody.empty();
                data.forEach(farm => {
                    tbody.append(`
                        <tr>
                            <td>${farm.branch_name}</td>
                            <td>${farm.supervisor_name}</td>
                            <td>${farm.broiler_place_name}</td>
                            <td>${farm.farm_name}</td>
                            <td>
                                <button class="btn btn-warning btn-sm edit-farm" data-id="${farm.id}">Edit</button>
                                <button class="btn btn-danger btn-sm delete-farm" data-id="${farm.id}">Delete</button>
                            </td>
                        </tr>
                    `);
                });
    
                // Reinitialize the DataTable
                table.DataTable({
                    destroy: true,
                    responsive: true, // Optional: Better for smaller screens
                    retrieve: true, // Prevent multiple initializations
                    paging: true,  // Enable pagination
                    searching: true, // Enable search filter
                    info: true     // Display "Showing X to Y of Z entries"
                });
            },
            error: function () {
                alert("Error loading farms. Please try again.");
            }
        });
    }
    

    // Load farms on page load
    loadFarms();
    // On branch selection, fetch supervisors
    $('#branch').change(function() {
        const branchId = $(this).val();
        if (branchId) {
            $.ajax({
                url: "{% url 'get_supervisors' %}",
                data: { branch_id: branchId },
                success: function(data) {
                    const supervisors = data.supervisors;
                    const supervisorSelect = $('#supervisor');
                    supervisorSelect.empty();
                    supervisorSelect.append('<option value="" selected disabled>Select a supervisor</option>');
                    supervisors.forEach(function(supervisor) {
                        supervisorSelect.append(`<option value="${supervisor.id}">${supervisor.name}</option>`);
                    });
                }
            });
        }
    });

    // On supervisor selection, fetch places
    $('#supervisor').change(function() {
        const supervisorId = $(this).val();
        if (supervisorId) {
            $.ajax({
                url: "{% url 'get_broiler_places' %}",
                data: { supervisor_id: supervisorId },
                success: function(data) {
                    const places = data.broiler_places;
                    const placeSelect = $('#broiler_place');
                    placeSelect.empty();
                    placeSelect.append('<option value="" selected disabled>Select a broiler place</option>');
                    places.forEach(function(place) {
                        placeSelect.append(`<option value="${place.id}">${place.place_name}</option>`);
                    });
                }
            });
        }
    });

    // Handle form submission
    $("#farm-form").submit(function (e) {
        e.preventDefault();
        const formData = {
            branch_id: $("#branch").val(),
            supervisor_id: $("#supervisor").val(),
            broiler_place_id: $("#broiler_place").val(),
            farm_code: $("#farm_code").val(),
            farm_name: $("#farm_name").val(),
            mobile_no: $("#mobile_no").val(),
            block_name: $("#block_name").val(),
            address: $("#address").val(),
            farm_latitude: $("#farm_latitude").val(),
            farm_longitude: $("#farm_longitude").val(),
            farm_type: $("#farm_type").val(),
        };

        $.ajax({
            url: "/broiler_farm_create/",
            type: "POST",
            data: formData,
            headers: {
                "X-CSRFToken": getCSRFToken()
            },
            success: function () {
                $("#farmFormModal").modal("hide");
                 // Reset the form
                $("#farm-form")[0].reset();

                // Clear dependent dropdowns
                $("#supervisor").empty().append('<option value="" selected disabled>Select a supervisor</option>');
                $("#broiler_place").empty().append('<option value="" selected disabled>Select a broiler place</option>');
                loadFarms();
                alert("Farm added successfully!");
            },
            error: function (xhr) {
                alert("Error adding farm. Please check your input.");
            }
        });
    });

    // Handle edit button click
    $(document).on("click", ".edit-farm", function () {
        const farmId = $(this).data("id");
        $.ajax({
            url: `/broiler_farm/${farmId}/`,
            type: "GET",
            success: function (farm) {
                $("#branch").val(farm.branch);
                $("#supervisor").val(farm.supervisor);
                $("#broiler_place").val(farm.place);
                $("#farm_code").val(farm.farm_code);
                $("#farm_name").val(farm.farm_name);
                $("#mobile_no").val(farm.mobile_no);
                $("#block_name").val(farm.block_name);
                $("#address").val(farm.address);
                $("#farm_latitude").val(farm.farm_latitude);
                $("#farm_longitude").val(farm.farm_longitude);
                $("#farm_type").val(farm.farm_type);
                $("#farmFormModal").modal("show");

                // Update form submit behavior
                $("#farm-form").off("submit").on("submit", function (e) {
                    e.preventDefault();
                    const updatedData = {
                        branch: $("#branch").val(),
                        supervisor: $("#supervisor").val(),
                        broiler_place: $("#broiler_place").val(),
                        farm_code: $("#farm_code").val(),
                        farm_name: $("#farm_name").val(),
                        mobile_no: $("#mobile_no").val(),
                        block_name: $("#block_name").val(),
                        address: $("#address").val(),
                        farm_latitude: $("#farm_latitude").val(),
                        farm_longitude: $("#farm_longitude").val(),
                        farm_type: $("#farm_type").val(),
                    };

                    $.ajax({
                        url: `/broiler_farm/${farmId}/update/`,
                        type: "PUT",
                        data: JSON.stringify(updatedData),
                        contentType: "application/json",
                        headers: {
                            "X-CSRFToken": getCSRFToken()
                        },
                        success: function () {
                            $("#farmFormModal").modal("hide");
                            loadFarms();
                            alert("Farm updated successfully!");
                        },
                        error: function (xhr) {
                            alert("Error updating farm.");
                        }
                    });
                });
            },
            error: function () {
                alert("Error fetching farm details.");
            }
        });
    });

    // Handle delete button click
    $(document).on("click", ".delete-farm", function () {
        const farmId = $(this).data("id");
        if (confirm("Are you sure you want to delete this farm?")) {
            $.ajax({
                url: `/broiler_farm/${farmId}/delete/`,
                type: "DELETE",
                headers: {
                    "X-CSRFToken": getCSRFToken()
                },
                success: function () {
                    loadFarms();
                    alert("Farm deleted successfully!");
                },
                error: function () {
                    alert("Error deleting farm.");
                }
            });
        }
    });
});