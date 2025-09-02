$(document).ready(function() {
    // Sidebar toggle
    $('#sidebarCollapse').on('click', function() {
        $('#sidebar, #content').toggleClass('collapsed');
    });

    // Initialize DataTables
    $('table').each(function() {
        if (!$.fn.DataTable.isDataTable(this)) {
            $(this).DataTable({
                pageLength: 10,
                lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, "All"]],
                responsive: true
            });
        }
    });

    // Auto-capitalize insurance code inputs
    $('input[name="InsuranceCode"]').on('input', function() {
        this.value = this.value.toUpperCase();
    });

    // Form validation
    $('form').on('submit', function() {
        const submitBtn = $(this).find('button[type="submit"]');
        submitBtn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Processing...');
    });

    // Toggle password visibility
    $('.toggle-password').on('click', function() {
        const input = $(this).closest('.input-group').find('input');
        const type = input.attr('type') === 'password' ? 'text' : 'password';
        input.attr('type', type);
        $(this).find('i').toggleClass('fa-eye fa-eye-slash');
    });

    // File upload validation
    $('input[type="file"]').on('change', function() {
        const file = this.files[0];
        if (file) {
            const fileSize = file.size / 1024 / 1024; // in MB
            if (fileSize > 10) {
                alert('File size exceeds 10MB limit. Please choose a smaller file.');
                this.value = '';
            }
            
            const extension = file.name.split('.').pop().toLowerCase();
            if (['xlsx', 'xls'].indexOf(extension) === -1) {
                alert('Please select an Excel file (xlsx or xls format).');
                this.value = '';
            }
        }
    });
});