$(document).ready(function () {
    // Load Broiler Batch List
    function loadBatchList() {
        $.ajax({
            url: "{% url 'broiler_batch_list' %}",
            type: "GET",
            success: function (response) {
                const table = $("#broiler-batch-table");
                const tableBody = table.find("tbody");

                // Destroy existing DataTable instance if it exists
                if ($.fn.DataTable.isDataTable(table)) {
                    table.DataTable().clear().destroy();
                }
                tableBody.empty();

                // Generate table rows and modals dynamically
                response.forEach((batch) => {
                    const modalId = `editBatchModal-${batch.id}`;
                    const formId = `edit-batch-form-${batch.id}`;
                    const tableRow = `
                        <tr>
                            <td>${batch.broiler_farm_name}</td>
                            <td>${batch.batch_name}</td>
                            <td>
                                <button class="btn btn-warning btn-sm edit-button" 
                                    data-bs-toggle="modal" 
                                    data-bs-target="#${modalId}" 
                                    data-id="${batch.id}" 
                                    data-broiler-farm="${batch.broiler_farm}" 
                                    data-batch-name="${batch.batch_name}">
                                    Edit
                                </button>
                                <button class="btn btn-danger btn-sm delete-button" 
                                    data-id="${batch.id}">
                                    Delete
                                </button>
                            </td>
                        </tr>
                    `;

                    const modal = `
                        <div class="modal fade" id="${modalId}" tabindex="-1" aria-labelledby="${modalId}-Label" aria-hidden="true">
                            <div class="modal-dialog">
                                <div class="modal-content">
                                    <div class="modal-header">
                                        <h5 class="modal-title">Edit Batch</h5>
                                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                    </div>
                                    <form id="${formId}">
                                        <div class="modal-body">
                                            <input type="hidden" name="batch-id" value="${batch.id}">
                                            <div class="mb-3">
                                                <label class="form-label">Broiler Farm</label>
                                                <input type="text" class="form-control" name="broiler_farm" value="${batch.broiler_farm}" required>
                                            </div>
                                            <div class="mb-3">
                                                <label class="form-label">Batch Name</label>
                                                <input type="text" class="form-control" name="batch_name" value="${batch.batch_name}" required>
                                            </div>
                                        </div>
                                        <div class="modal-footer">
                                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                                            <button type="submit" class="btn btn-primary">Save Changes</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                    `;

                    tableBody.append(tableRow);
                    $("body").append(modal);

                    // Add form submission handling for each dynamic modal
                    $(`#${formId}`).off("submit").on("submit", function (e) {
                        e.preventDefault();
                        const jsonData = {
                            batch_id: $(`#${formId} [name="batch-id"]`).val(),
                            broiler_farm: $(`#${formId} [name="broiler_farm"]`).val(),
                            batch_name: $(`#${formId} [name="batch_name"]`).val(),
                        };

                        $.ajax({
                            url: `/broiler_batch/${batch.id}/update/`,
                            type: "POST",
                            headers: {
                                "X-CSRFToken": "{{ csrf_token }}",
                            },
                            data: jsonData,
                            success: function () {
                                loadBatchList();
                                $(`#${modalId}`).modal("hide");
                            },
                            error: function (xhr) {
                                alert("Failed to update batch. Please try again.");
                            },
                        });
                    });
                });

                // Reinitialize DataTable
                table.DataTable({
                    responsive: true,
                    paging: true,
                    searching: true,
                    info: true,
                    lengthChange: true,
                    columnDefs: [
                        { orderable: false, targets: -1 },
                    ],
                });
            },
            error: function (xhr) {
                alert("Error loading batch list. Please try again.");
            },
        });
    }

    loadBatchList();

    // Add Broiler Batch
    $("#broiler-batch-form").on("submit", function (e) {
        e.preventDefault();
        const broilerFarmId = $("#broiler_farm").val();
        const batchName = $("#batch_name").val();
        $.ajax({
            url: "{% url 'broiler_batch_create' %}",
            type: "POST",
            headers: {
                "X-CSRFToken": "{{ csrf_token }}",
            },
            data: {
                broiler_farm_id: broilerFarmId,
                batch_name: batchName,
            },
            success: function () {
                loadBatchList();
                $("#batchFormModal").modal("hide");
                $("#broiler-batch-form").trigger("reset");
            },
            error: function () {
                alert("Failed to add new batch.");
            },
        });
    });

    // Delete Broiler Batch
    $(document).on("click", ".delete-button", function () {
        const id = $(this).data("id");

        if (confirm("Are you sure you want to delete this batch?")) {
            $.ajax({
                url: `/broiler_batch/${id}/delete/`,
                method: "DELETE",
                headers: { "X-CSRFToken": "{{ csrf_token }}" },
                success: function () {
                    loadBatchList();
                    alert("Batch deleted successfully!");
                },
                error: function () {
                    alert("An error occurred while deleting the batch.");
                },
            });
        }
    });
});