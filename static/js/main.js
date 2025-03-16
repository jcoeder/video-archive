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
    const addCategoryModal = document.getElementById('addCategoryModal');
    const modal = addCategoryModal ? bootstrap.Modal.getOrCreateInstance(addCategoryModal) : null;

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
                    // Add new category to the dropdown in the modal
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

                    // Close the modal
                    if (modal) {
                        modal.hide();
                    }

                    // Show success toast
                    const toast = new bootstrap.Toast(document.createElement('div'));
                    toast.element.className = 'toast align-items-center text-bg-success border-0 position-fixed bottom-0 end-0 m-3';
                    toast.element.innerHTML = `
                        <div class="d-flex">
                            <div class="toast-body">
                                Category added successfully!
                            </div>
                            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                        </div>
                    `;
                    document.body.appendChild(toast.element);
                    toast.show();

                    // Remove toast after it's hidden
                    toast.element.addEventListener('hidden.bs.toast', () => {
                        toast.element.remove();
                    });
                } else {
                    // Show error toast
                    const toast = new bootstrap.Toast(document.createElement('div'));
                    toast.element.className = 'toast align-items-center text-bg-danger border-0 position-fixed bottom-0 end-0 m-3';
                    toast.element.innerHTML = `
                        <div class="d-flex">
                            <div class="toast-body">
                                ${data.error}
                            </div>
                            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                        </div>
                    `;
                    document.body.appendChild(toast.element);
                    toast.show();

                    // Remove toast after it's hidden
                    toast.element.addEventListener('hidden.bs.toast', () => {
                        toast.element.remove();
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