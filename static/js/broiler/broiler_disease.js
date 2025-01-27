$(document).ready(function () {
    // Load Disease List
    function loadDiseaseList() {
        $.ajax({
            url: "{% url 'broiler_disease_list' %}",
            type: "GET",
            success: function (response) {
                const table = $("#disease-table");
    
                // Destroy existing DataTable instance if it exists
                if ($.fn.DataTable.isDataTable(table)) {
                    table.DataTable().clear().destroy();
                }
    
                // Populate the table body with the new data
                let rows = "";
                response.forEach(function (item) {
                    rows += `
                    <tr>
                        <td>${item.disease_code}</td>
                        <td>${item.disease_name}</td>
                        <td>${item.symptoms}</td>
                        <td>${item.diagnosis}</td>
                        <td><img src="${item.image}" alt="Disease Image" class="img-fluid" style="max-width: 100px; height: auto;"></td>
                        <td>
                            <button class="btn btn-warning btn-sm edit-button" 
                                    data-id="${item.id}" 
                                    data-code="${item.disease_code}" 
                                    data-name="${item.disease_name}" 
                                    data-symptoms="${item.symptoms}" 
                                    data-diagnosis="${item.diagnosis}" 
                                    data-image="${item.image}">Edit</button>
                            <button class="btn btn-danger btn-sm delete-button" 
                                    data-id="${item.id}">Delete</button>
                        </td>
                    </tr>`;
                });
                table.find("tbody").html(rows);
    
                // Reinitialize DataTable with proper options
                table.DataTable({
                    destroy: true, // Ensure no duplicate initialization
                    responsive: true, // Make the table responsive
                    paging: true, // Enable pagination
                    searching: true, // Enable search functionality
                    info: true, // Show "Showing X to Y of Z entries"
                    lengthChange: true, // Allow page size selection
                    columnDefs: [
                        { orderable: false, targets: -1 } // Disable sorting for the actions column (last column)
                    ]
                });
            },
            error: function (xhr) {
                alert("Error loading disease list. Please try again.");
            }
        });
    }
    
    loadDiseaseList();

    // Add New Disease
    $("#disease-form").submit(function (e) {
        e.preventDefault();
        let formData = new FormData();
        formData.append("disease_code", $("#disease_code").val());
        formData.append("disease_name", $("#disease_name").val());
        formData.append("symptoms", $("#symptoms").val());
        formData.append("diagnosis", $("#diagnosis").val());
        formData.append("image", $("#image")[0].files[0]);
        formData.append("csrfmiddlewaretoken", "{{ csrf_token }}");

        $.ajax({
            url: "{% url 'broiler_disease_create' %}",
            type: "POST",
            processData: false,
            contentType: false,
            data: formData,
            success: function () {
                $("#diseaseFormModal").modal("hide");
                $("#disease-form").trigger("reset");
                loadDiseaseList();
            },
            error: function () {
                alert("An error occurred while adding the disease.");
            },
        });
    });

    // Edit Disease
    $(document).on("click", ".edit-button", function () {
        const id = $(this).data("id");
        $("#diseaseFormModalLabel").text("Edit Disease");
        $("#diseaseFormModal").modal("show");
        $("#disease_code").val($(this).data("code"));
        $("#disease_name").val($(this).data("name"));
        $("#symptoms").val($(this).data("symptoms"));
        $("#diagnosis").val($(this).data("diagnosis"));

        $("#disease-form").off("submit").on("submit", function (e) {
            e.preventDefault();
            let formData = new FormData();
            formData.append("disease_code", $("#disease_code").val());
            formData.append("disease_name", $("#disease_name").val());
            formData.append("symptoms", $("#symptoms").val());
            formData.append("diagnosis", $("#diagnosis").val());
            if ($("#image")[0].files[0]) {
                formData.append("image", $("#image")[0].files[0]);
            }
            formData.append("csrfmiddlewaretoken", "{{ csrf_token }}");

            $.ajax({
                url: `/broiler_disease/${id}/update/`,
                type: "POST",
                processData: false,
                contentType: false,
                data: formData,
                success: function () {
                    $("#diseaseFormModal").modal("hide");
                    $("#disease-form").trigger("reset");
                    loadDiseaseList();
                },
                error: function () {
                    alert("An error occurred while updating the disease.");
                },
            });
        });
    });

    // Delete Disease
    $(document).on("click", ".delete-button", function () {
        const id = $(this).data("id");
        const csrfToken = "{{ csrf_token }}";

        if (confirm("Are you sure you want to delete this disease?")) {
            $.ajax({
                url: `/broiler_disease/${id}/delete/`,
                type: "DELETE",
                headers: { "X-CSRFToken": csrfToken },
                success: function () {
                    alert("Disease deleted successfully!");
                    loadDiseaseList();
                },
                error: function () {
                    alert("An error occurred while deleting the disease.");
                },
            });
        }
    });
});