$(document).ready(function () {
    const requiredFields = [
        'full_name', 'father_name',
        'date_of_birth', 'designation', 'salary', 'blood_group',
        'qualification', 'pan_card', 'aadhar_number', 'emergency_contact', 'personal_contact',
        'country', 'correspondence_address', 'sector', 'group',
        'salary_type', 'date_of_joining', 'salary_account', 'bank_name', 'ifsc_code',
        'branch_name', 'saving'
    ];

    function removeError(field) {
        $(`#${field}`)
            .removeClass('error')
            .parent()
            .find('.error-message')
            .remove();
    }

    function addError(field, message) {
        const $field = $(`#${field}`);
        $field.addClass('error');

        $field.parent().find('.error-message').remove();

        $('<div>')
            .addClass('error-message')
            .text(message)
            .insertAfter($field);
    }

    function calculateAge(dob) {
        const birthDate = new Date(dob);
        const today = new Date();
        const age = today.getFullYear() - birthDate.getFullYear();
        const month = today.getMonth() - birthDate.getMonth();

        if (month < 0 || (month === 0 && today.getDate() < birthDate.getDate())) {
            return age - 1;
        }
        return age;
    }

    function validateField(field) {
        const value = $(`#${field}`).val().trim();

        if ((field === 'personal_contact' || field === 'emergency_contact')) {
            if (!value) {
                addError(field, 'This field is required');
                return false;
            }

            if (!/^\d{10}$/.test(value)) {
                addError(field, 'Please enter a valid 10-digit number');
                return false;
            }
        }

        else if (field === 'aadhar_number') {
            if (!value) {
                addError(field, 'This field is required');
                return false;
            }

            if (!/^\d{12}$/.test(value)) {
                addError(field, 'Please enter a valid 12-digit Aadhar number');
                return false;
            }
        }
        else if (field === 'pan_card') {
            if (!value) {
                addError(field, 'This field is required');
                return false;
            }
        
            if (!/^[A-Z]{5}\d{4}[A-Z]{1}$/.test(value)) {
                addError(field, 'Please enter a valid 10-character PAN Card (e.g., AAAAA9999A)');
                return false;
            }
        }  
        else if (field === 'date_of_birth') {
            if (!value) {
                addError(field, 'This field is required');
                return false;
            }

            const age = calculateAge(value);
            if (age < 18) {
                addError(field, 'You must be at least 18 years old');
                return false;
            }
        }
        else {
            if (!value) {
                addError(field, 'This field is required');
                return false;
            }
        }

        removeError(field);
        return true;
    }

    // Attach event listeners for input and blur events
    requiredFields.forEach(field => {
        $(`#${field}`).on('input blur', function () {
            validateField(field);
        });
    });

    // Handle form submission
    $('#employee-form').on('submit', function (event) {
        let isValid = true;

        requiredFields.forEach(field => {
            if (!validateField(field)) {
                isValid = false;
            }
        });

        if (!isValid) {
            event.preventDefault();
            $('html, body').animate({
                scrollTop: $('.error:first').offset().top - 100
            }, 500);
        }
    });
});
