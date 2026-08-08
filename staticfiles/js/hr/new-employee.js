$(document).ready(function () {
    // Only what the form actually marks with a red asterisk.
    //
    // This list used to hold eleven fields — father's name, date of birth,
    // qualification, designation, salary, country, group, salary type and
    // contact among them — every one of them nullable in the database, and
    // only two of them marked on the form. So an employee saved years ago
    // could not be reopened and corrected without first filling in details
    // nobody had ever collected, and the form gave no warning until Save
    // refused.
    //
    // Designation is not here either: it is nullable, and its picker had no
    // empty option, so the check could never fail — val() returned whichever
    // designation happened to be first and the form posted it.
    const requiredFields = ['full_name', 'warehouse'];

    // Fields with a shape to keep. Checked only once something is typed: an
    // empty box is now a blank, not a mistake, but a phone number that is
    // there has to be a phone number.
    const formatFields = [
        'personal_contact', 'emergency_contact',
        'aadhar_number', 'pan_card', 'date_of_birth',
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
        const $field = $(`#${field}`);
        // A field the template does not render at all (the add and edit forms
        // do not carry exactly the same set) is nothing to complain about.
        if (!$field.length) return true;
        const value = ($field.val() || '').trim();

        if (!value) {
            // Blank is only a problem for the two the form marks.
            if (requiredFields.indexOf(field) === -1) {
                removeError(field);
                return true;
            }
            addError(field, 'This field is required');
            return false;
        }

        if (field === 'personal_contact' || field === 'emergency_contact') {
            if (!/^\d{10}$/.test(value)) {
                addError(field, 'Please enter a valid 10-digit number');
                return false;
            }
        } else if (field === 'aadhar_number') {
            if (!/^\d{12}$/.test(value)) {
                addError(field, 'Please enter a valid 12-digit Aadhar number');
                return false;
            }
        } else if (field === 'pan_card') {
            if (!/^[A-Z]{5}\d{4}[A-Z]{1}$/.test(value)) {
                addError(field, 'Please enter a valid 10-character PAN Card (e.g., AAAAA9999A)');
                return false;
            }
        } else if (field === 'date_of_birth') {
            const age = calculateAge(value);
            if (age < 18) {
                addError(field, 'You must be at least 18 years old');
                return false;
            }
        }

        removeError(field);
        return true;
    }

    // Watch the marked fields and the ones with a shape to keep.
    requiredFields.concat(formatFields).forEach(field => {
        $(`#${field}`).on('input blur', function () {
            validateField(field);
        });
    });

    // Handle form submission
    $('#employee-form').on('submit', function (event) {
        let isValid = true;

        requiredFields.concat(formatFields).forEach(field => {
            if (!validateField(field)) {
                isValid = false;
            }
        });

        if (!isValid) {
            event.preventDefault();
            // Every failing field is on this form, but one of them may be a
            // format error on a field this template does not render, in which
            // case there is nothing to scroll to.
            const $first = $('.error:first');
            if ($first.length) {
                $('html, body').animate({ scrollTop: $first.offset().top - 100 }, 500);
            }
        }
    });
});