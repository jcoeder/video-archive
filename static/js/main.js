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

// Show loading state and progress during video upload
document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('uploadForm');
    const uploadButton = document.getElementById('uploadButton');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const progressBar = document.getElementById('uploadProgress');
    const progressBarInner = progressBar.querySelector('.progress-bar');
    const uploadStatus = document.getElementById('uploadStatus');
    const videoInput = document.getElementById('video');
    const youtubeUrlInput = document.getElementById('youtubeUrl');

    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);

            // Check if it's a file upload or YouTube URL
            if (videoInput.files.length > 0) {
                // Show progress bar for file uploads
                progressBar.classList.remove('d-none');
                uploadButton.disabled = true;
                loadingSpinner.classList.remove('d-none');

                const xhr = new XMLHttpRequest();
                xhr.open('POST', uploadForm.action, true);

                xhr.upload.onprogress = function(e) {
                    if (e.lengthComputable) {
                        const percentComplete = (e.loaded / e.total) * 100;
                        progressBarInner.style.width = percentComplete + '%';
                        progressBarInner.textContent = Math.round(percentComplete) + '%';
                        progressBarInner.setAttribute('aria-valuenow', percentComplete);
                    }
                };

                xhr.onload = function() {
                    if (xhr.status === 200) {
                        // Upload complete, now processing
                        progressBar.classList.add('d-none');
                        uploadStatus.classList.remove('d-none');
                        window.location.href = xhr.responseURL || '/';
                    } else {
                        uploadButton.disabled = false;
                        loadingSpinner.classList.add('d-none');
                        progressBar.classList.add('d-none');
                        alert('Upload failed. Please try again.');
                    }
                };

                xhr.onerror = function() {
                    uploadButton.disabled = false;
                    loadingSpinner.classList.add('d-none');
                    progressBar.classList.add('d-none');
                    alert('Upload failed. Please try again.');
                };

                xhr.send(formData);
            } else if (youtubeUrlInput.value) {
                // For YouTube URLs, show processing status
                uploadButton.disabled = true;
                loadingSpinner.classList.remove('d-none');
                uploadStatus.classList.remove('d-none');

                fetch(uploadForm.action, {
                    method: 'POST',
                    body: formData
                }).then(response => {
                    if (response.ok) {
                        window.location.href = response.url;
                    } else {
                        throw new Error('YouTube processing failed');
                    }
                }).catch(error => {
                    uploadButton.disabled = false;
                    loadingSpinner.classList.add('d-none');
                    uploadStatus.classList.add('d-none');
                    alert('Processing failed. Please try again.');
                });
            }
        });
    }

    // YouTube URL validation
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

    // Category form handling - unified for all pages
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
                    // Add new checkbox to the categories container
                    const categoriesContainer = document.getElementById('categoriesContainer');
                    const newCategory = document.createElement('div');
                    newCategory.className = 'form-check';
                    newCategory.innerHTML = `
                        <input class="form-check-input" type="checkbox" name="categories" 
                               value="${data.category.id}" id="category${data.category.id}" checked>
                        <label class="form-check-label" for="category${data.category.id}">
                            ${data.category.name}
                        </label>
                    `;

                    // Insert the new category in alphabetical order
                    const categories = Array.from(categoriesContainer.children);
                    const insertIndex = categories.findIndex(cat => {
                        const label = cat.querySelector('label');
                        return label && label.textContent.trim().localeCompare(data.category.name) > 0;
                    });

                    if (insertIndex === -1) {
                        categoriesContainer.appendChild(newCategory);
                    } else {
                        categoriesContainer.insertBefore(newCategory, categories[insertIndex]);
                    }

                    categoryInput.value = ''; // Clear input
                    categoryInput.focus(); // Keep focus on input field

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
                        delay: 3000,
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