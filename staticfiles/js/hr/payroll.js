$(document).ready(function() {
    function processPayroll() {
        const employee = document.getElementById('employeeSelect');
        const year = document.getElementById('yearSelect');
        const month = document.getElementById('monthSelect');
    
        // Basic validation
        if (!employee.value || !year.value || !month.value) {
            alert('Please fill in all fields');
            return;
        }
    
        $.ajax({
            url: '/payroll/',
            method: 'POST',
            data: {
                employee_id: employee.value,
                year: year.value,
                month: month.value
            },
            success: function(response) {
                dynamicloadtable(response);
            },
            error: function(xhr, status, error) {
                let response = JSON.parse(xhr.responseText);
                alert(response.message);  // UI me error show karega
            }
        });
    }

    function dynamicloadtable(response) {
        // Extract data from the response
        const { employee, year, month, total_working_days, payable_salary, gross_salary } = response;
    
        // Create a new table row with the data
        const newRow = `
            <tr>
                <td>${employee}</td>
                <td>${year}</td>
                <td>${month}</td>
                <td>${total_working_days}</td>
                <td>${payable_salary}</td>
                <td>${gross_salary}</td>
            </tr>
        `;
    
        // Append the new row to the table body
        const payrollResults = document.getElementById('payrollResults');
        payrollResults.innerHTML = newRow; // Overwrite the existing rows (if any)
    }

    const yearSelect = document.getElementById('yearSelect');
        const currentYear = new Date().getFullYear();
        const startYear = currentYear - 5; // Adjust range as needed

        for (let year = currentYear; year >= startYear; year--) {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            yearSelect.appendChild(option);
        }

        // Generate month options dynamically
        const monthSelect = document.getElementById('monthSelect');
        const monthNames = [
            "January", "February", "March", "April", "May", 
            "June", "July", "August", "September", "October", 
            "November", "December"
        ];

        monthNames.forEach((month, index) => {
            const option = document.createElement('option');
            option.value = String(index + 1).padStart(2, '0'); // Format as "01", "02", etc.
            option.textContent = month;
            monthSelect.appendChild(option);
        });
    $('#generatepayroll').on('click', function(){      
        processPayroll();
    });
});