// Video preview on hover
const videoCards = document.querySelectorAll('.video-card');
videoCards.forEach(card => {
    const previewVideo = card.querySelector('.video-preview');
    const thumbnail = card.querySelector('.video-thumbnail');

    if (previewVideo && thumbnail) {
        let timeoutId;

        thumbnail.addEventListener('mouseenter', () => {
            timeoutId = setTimeout(() => {
                thumbnail.style.display = 'none';
                previewVideo.style.display = 'block';
                previewVideo.play().catch(e => console.log('Preview autoplay prevented'));
            }, 500); // Start preview after 500ms hover
        });

        thumbnail.addEventListener('mouseleave', () => {
            clearTimeout(timeoutId);
            previewVideo.style.display = 'none';
            thumbnail.style.display = 'block';
            previewVideo.pause();
            previewVideo.currentTime = 0;
        });
    }
});

// Show loading state during video upload
document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    const uploadButton = document.getElementById('uploadButton');
    const loadingSpinner = document.getElementById('loadingSpinner');

    if (uploadForm) {
        uploadForm.addEventListener('submit', function() {
            uploadButton.disabled = true;
            loadingSpinner.classList.remove('d-none');
        });
    }

    // YouTube URL validation
    const youtubeUrlInput = document.getElementById('youtubeUrl');
    if (youtubeUrlInput) {
        youtubeUrlInput.addEventListener('input', function() {
            const url = this.value;
            const youtubeRegex = /^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$/;
            if (!youtubeRegex.test(url)) {
                this.setCustomValidity('Please enter a valid YouTube URL');
            } else {
                this.setCustomValidity('');
            }
        });
    }

    // Add category form handling
    const categoryForm = document.getElementById('categoryForm');
    if (categoryForm) {
        categoryForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const categoryInput = categoryForm.querySelector('input[name="category_name"]');
            const categoryName = categoryInput.value;

            fetch('/category/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `category_name=${encodeURIComponent(categoryName)}`
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Add new category to the list
                    const categoriesContainer = document.getElementById('categoriesContainer');
                    const newCategory = document.createElement('div');
                    newCategory.className = 'form-check';
                    newCategory.innerHTML = `
                        <input class="form-check-input" type="checkbox" name="categories" 
                               value="${data.category.id}" id="category${data.category.id}">
                        <label class="form-check-label" for="category${data.category.id}">
                            ${data.category.name}
                        </label>
                    `;
                    categoriesContainer.appendChild(newCategory);
                    categoryInput.value = ''; // Clear input

                    // Show success notification
                    const toastDiv = document.createElement('div');
                    toastDiv.className = 'toast align-items-center text-bg-success border-0 position-fixed bottom-0 end-0 m-3';
                    toastDiv.setAttribute('role', 'alert');
                    toastDiv.setAttribute('aria-live', 'assertive');
                    toastDiv.setAttribute('aria-atomic', 'true');
                    toastDiv.innerHTML = `
                        <div class="d-flex">
                            <div class="toast-body">
                                Category added
                            </div>
                        </div>
                    `;
                    document.body.appendChild(toastDiv);

                    const toast = new bootstrap.Toast(toastDiv, {
                        delay: 3000, // Auto-hide after 3 seconds
                        animation: true
                    });
                    toast.show();

                    // Remove toast element after it's hidden
                    toastDiv.addEventListener('hidden.bs.toast', () => {
                        toastDiv.remove();
                    });
                }
            });
        });
    }

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });
});