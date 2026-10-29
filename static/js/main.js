/**
 * CampusConnect - Vanilla JavaScript Interactions
 * ------------------------------------------------
 * Handles responsive navigation, interactive horizontal showcase rail
 * (momentum drag, arrow buttons, keyboard navigation), filter tabs,
 * PIN visibility toggle with icons, and form validation helpers.
 */

// Global function to toggle PIN visibility between password and plain text
function togglePin(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;

    const btn = input.parentElement ? input.parentElement.querySelector('.btn-pin-toggle') : null;

    if (input.type === 'password') {
        input.type = 'text';
        if (btn) {
            btn.textContent = '🙈';
            btn.setAttribute('aria-label', 'Hide PIN');
        }
    } else {
        input.type = 'password';
        if (btn) {
            btn.textContent = '👁️';
            btn.setAttribute('aria-label', 'Show PIN');
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // -------------------------------------------------------------------------
    // 1. Mobile Navigation Drawer Toggle
    // -------------------------------------------------------------------------
    const navToggle = document.getElementById('navToggle');
    const navMenu = document.getElementById('navMenu');

    if (navToggle && navMenu) {
        navToggle.addEventListener('click', () => {
            const isOpen = navMenu.classList.toggle('open');
            navToggle.classList.toggle('open', isOpen);
            navToggle.setAttribute('aria-expanded', isOpen);
        });

        // Close menu if clicking outside on mobile
        document.addEventListener('click', (e) => {
            if (navMenu.classList.contains('open') &&
                !navMenu.contains(e.target) &&
                !navToggle.contains(e.target)) {
                navMenu.classList.remove('open');
                navToggle.classList.remove('open');
                navToggle.setAttribute('aria-expanded', 'false');
            }
        });

        // Close menu on Escape key press
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && navMenu.classList.contains('open')) {
                navMenu.classList.remove('open');
                navToggle.classList.remove('open');
                navToggle.setAttribute('aria-expanded', 'false');
                navToggle.focus();
            }
        });
    }

    // -------------------------------------------------------------------------
    // 2. Interactive Campus Discovery Rail (Horizontal Sliding Showcase)
    // -------------------------------------------------------------------------
    const railViewport = document.getElementById('railViewport');
    const railTrack = document.getElementById('railTrack');
    const railPrevBtn = document.getElementById('railPrevBtn');
    const railNextBtn = document.getElementById('railNextBtn');

    if (railViewport && railTrack) {
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const scrollBehavior = prefersReducedMotion ? 'auto' : 'smooth';

        const getScrollStep = () => {
            const firstCard = railTrack.querySelector('.rail-card-wrapper');
            if (firstCard) {
                // Card width + margin gap
                return firstCard.offsetWidth + 20;
            }
            return 320;
        };

        // Arrow Buttons Navigation
        if (railPrevBtn) {
            railPrevBtn.addEventListener('click', () => {
                railViewport.scrollBy({ left: -getScrollStep() * 1.5, behavior: scrollBehavior });
            });
        }

        if (railNextBtn) {
            railNextBtn.addEventListener('click', () => {
                railViewport.scrollBy({ left: getScrollStep() * 1.5, behavior: scrollBehavior });
            });
        }

        // Mouse Drag to Scroll (Physics-inspired 1D rail glide)
        let isDown = false;
        let startX = 0;
        let scrollLeft = 0;
        let isDragging = false;

        railViewport.addEventListener('mousedown', (e) => {
            // Ignore mousedown on links or buttons
            if (e.target.closest('a') || e.target.closest('button')) return;

            isDown = true;
            isDragging = false;
            railViewport.classList.add('is-dragging');
            startX = e.pageX - railViewport.offsetLeft;
            scrollLeft = railViewport.scrollLeft;
        });

        window.addEventListener('mouseup', () => {
            if (!isDown) return;
            isDown = false;
            railViewport.classList.remove('is-dragging');
            setTimeout(() => { isDragging = false; }, 50);
        });

        document.addEventListener('mouseleave', () => {
            if (isDown) {
                isDown = false;
                railViewport.classList.remove('is-dragging');
                setTimeout(() => { isDragging = false; }, 50);
            }
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDown) return;
            e.preventDefault();
            const x = e.pageX - railViewport.offsetLeft;
            const walk = (x - startX) * 1.35; // Scroll speed factor
            if (Math.abs(walk) > 6) {
                isDragging = true;
            }
            railViewport.scrollLeft = scrollLeft - walk;
        });

        // Prevent accidental link navigation when user drags across cards
        railTrack.addEventListener('click', (e) => {
            if (isDragging) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);

        // Keyboard Navigation (Left / Right arrow keys within rail)
        railViewport.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowRight') {
                e.preventDefault();
                railViewport.scrollBy({ left: getScrollStep(), behavior: scrollBehavior });
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                railViewport.scrollBy({ left: -getScrollStep(), behavior: scrollBehavior });
            }
        });
    }

    // -------------------------------------------------------------------------
    // 3. Filter Type Tabs, Search, Dropdowns, and Anchor Navigation
    // -------------------------------------------------------------------------
    const typeTabs = document.querySelectorAll('.type-tab-btn');
    const itemTypeInput = document.getElementById('itemTypeInput');
    const filterForm = document.getElementById('filterForm');
    const categorySelect = document.getElementById('categorySelect');
    const statusSelect = document.getElementById('statusSelect');
    const clearSearchBtn = document.getElementById('clearSearchBtn');

    function submitFilterForm(newType) {
        if (!filterForm) return;

        if (newType && itemTypeInput) {
            itemTypeInput.value = newType;
        }

        // Keep selected tabs visually active and update aria-selected immediately
        const activeType = (newType || (itemTypeInput ? itemTypeInput.value : 'all')) || 'all';
        typeTabs.forEach(t => {
            const isSelected = (t.getAttribute('data-type') === activeType);
            t.classList.toggle('active', isSelected);
            t.setAttribute('aria-selected', isSelected ? 'true' : 'false');
        });

        // Collect form data and build clean query string while preserving #itemsResults anchor
        const formData = new FormData(filterForm);
        const params = new URLSearchParams();
        for (const [key, value] of formData.entries()) {
            const trimmed = value.trim();
            if (trimmed) {
                params.set(key, trimmed);
            }
        }

        const baseUrl = (filterForm.getAttribute('action') || window.location.pathname).split('#')[0].split('?')[0];
        const queryString = params.toString();
        const targetUrl = baseUrl + (queryString ? '?' + queryString : '') + '#itemsResults';

        window.location.href = targetUrl;
    }

    if (filterForm) {
        // Intercept standard form submission (Enter key or Search button)
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            submitFilterForm();
        });

        // Tab click and WAI-ARIA keyboard navigation
        if (typeTabs.length > 0) {
            typeTabs.forEach((tab, index) => {
                tab.addEventListener('click', (e) => {
                    e.preventDefault();
                    const selectedType = tab.getAttribute('data-type');
                    submitFilterForm(selectedType);
                });

                tab.addEventListener('keydown', (e) => {
                    let targetIndex = null;
                    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                        e.preventDefault();
                        targetIndex = (index + 1) % typeTabs.length;
                    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                        e.preventDefault();
                        targetIndex = (index - 1 + typeTabs.length) % typeTabs.length;
                    } else if (e.key === 'Home') {
                        e.preventDefault();
                        targetIndex = 0;
                    } else if (e.key === 'End') {
                        e.preventDefault();
                        targetIndex = typeTabs.length - 1;
                    }

                    if (targetIndex !== null) {
                        typeTabs[targetIndex].focus();
                        const nextType = typeTabs[targetIndex].getAttribute('data-type');
                        submitFilterForm(nextType);
                    }
                });
            });
        }

        // Automatic submission on category / status dropdown changes
        if (categorySelect) {
            categorySelect.addEventListener('change', () => {
                submitFilterForm();
            });
        }

        if (statusSelect) {
            statusSelect.addEventListener('change', () => {
                submitFilterForm();
            });
        }
    }

    // Keyboard accessibility for Clear Search button (Space bar activation)
    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('keydown', (e) => {
            if (e.key === ' ' || e.key === 'Spacebar') {
                e.preventDefault();
                clearSearchBtn.click();
            }
        });
    }

    // Keyboard accessibility for active filter tag clear buttons
    document.querySelectorAll('.filter-tag-clear, .clear-all-link').forEach(btn => {
        btn.addEventListener('keydown', (e) => {
            if (e.key === ' ' || e.key === 'Spacebar') {
                e.preventDefault();
                btn.click();
            }
        });
    });

    // Smooth scroll to results anchor if URL has #itemsResults (respecting prefers-reduced-motion)
    if (window.location.hash === '#itemsResults') {
        const resultsEl = document.getElementById('itemsResults');
        if (resultsEl) {
            const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            setTimeout(() => {
                resultsEl.scrollIntoView({
                    behavior: prefersReducedMotion ? 'auto' : 'smooth',
                    block: 'start'
                });
            }, 30);
        }
    }

    // -------------------------------------------------------------------------
    // 4. Form Type Radio Card Highlighting (submit.html)
    // -------------------------------------------------------------------------
    const typeCards = document.querySelectorAll('.type-radio-card');
    typeCards.forEach(card => {
        const radio = card.querySelector('input[type="radio"]');
        if (radio) {
            radio.addEventListener('change', () => {
                typeCards.forEach(c => c.classList.remove('selected'));
                if (radio.checked) {
                    card.classList.add('selected');
                }
            });
        }
    });

    // -------------------------------------------------------------------------
    // 5. Client-Side Numeric Guard for PIN Inputs
    // -------------------------------------------------------------------------
    const pinInputs = document.querySelectorAll('input[pattern="[0-9]{4,8}"]');
    pinInputs.forEach(input => {
        input.addEventListener('input', (e) => {
            // Keep strictly digits
            e.target.value = e.target.value.replace(/[^0-9]/g, '');
        });
    });

    // -------------------------------------------------------------------------
    // 6. Photo Upload, Mobile Camera Capture & Instant Preview
    // -------------------------------------------------------------------------
    const cameraInput = document.getElementById('cameraInput');
    const fileInput = document.getElementById('fileInput');
    const btnTakePhoto = document.getElementById('btnTakePhoto');
    const btnUploadPhoto = document.getElementById('btnUploadPhoto');
    const photoActionButtons = document.getElementById('photoActionButtons');
    const photoHelpText = document.getElementById('photoHelpText');
    const photoPreviewCard = document.getElementById('photoPreviewCard');
    const photoPreviewImg = document.getElementById('photoPreviewImg');
    const previewFilename = document.getElementById('previewFilename');
    const previewFilesize = document.getElementById('previewFilesize');
    const btnRetakePhoto = document.getElementById('btnRetakePhoto');
    const btnRemovePhoto = document.getElementById('btnRemovePhoto');
    const photoErrorMessage = document.getElementById('photoErrorMessage');

    const MAX_PHOTO_BYTES = 5 * 1024 * 1024; // 5 MB
    const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp'];

    function showPhotoError(msg) {
        if (!photoErrorMessage) return;
        photoErrorMessage.textContent = msg;
        photoErrorMessage.style.display = 'block';
    }

    function clearPhotoError() {
        if (!photoErrorMessage) return;
        photoErrorMessage.textContent = '';
        photoErrorMessage.style.display = 'none';
    }

    function handleSelectedFile(file, activeInput) {
        clearPhotoError();
        if (!file) return;

        // Extension & Type checks
        const ext = file.name ? file.name.split('.').pop().toLowerCase() : '';
        const mime = file.type ? file.type.toLowerCase() : '';
        const isValidExt = ALLOWED_EXTENSIONS.includes(ext);
        const isValidMime = mime.startsWith('image/') || mime === '';

        if (!isValidExt && !isValidMime) {
            showPhotoError("Unsupported image format. Please select a JPEG, PNG, or WebP photo.");
            activeInput.value = '';
            return;
        }

        // File size check (5 MB limit)
        if (file.size > MAX_PHOTO_BYTES) {
            const sizeInMB = (file.size / (1024 * 1024)).toFixed(1);
            showPhotoError(`Selected photo is ${sizeInMB} MB. Maximum allowed image size is 5 MB.`);
            activeInput.value = '';
            return;
        }

        // Clear the inactive input so only one file is sent
        if (activeInput === cameraInput && fileInput) {
            fileInput.value = '';
        } else if (activeInput === fileInput && cameraInput) {
            cameraInput.value = '';
        }

        // Generate client-side preview
        const reader = new FileReader();
        reader.onload = function(e) {
            if (photoPreviewImg) {
                photoPreviewImg.src = e.target.result;
            }
            if (previewFilename) {
                previewFilename.textContent = file.name || 'Captured Photo';
            }
            if (previewFilesize) {
                const sizeDisplay = file.size > 1024 * 1024
                    ? `${(file.size / (1024 * 1024)).toFixed(2)} MB`
                    : `${Math.round(file.size / 1024)} KB`;
                previewFilesize.textContent = sizeDisplay;
            }

            if (photoActionButtons) photoActionButtons.style.display = 'none';
            if (photoHelpText) photoHelpText.style.display = 'none';
            if (photoPreviewCard) photoPreviewCard.style.display = 'flex';
        };
        reader.onerror = function() {
            showPhotoError("Unable to read selected photo file. Please try another image.");
        };
        reader.readAsDataURL(file);
    }

    if (btnTakePhoto && cameraInput) {
        btnTakePhoto.addEventListener('click', () => {
            clearPhotoError();
            cameraInput.click();
        });
        cameraInput.addEventListener('change', () => {
            if (cameraInput.files && cameraInput.files[0]) {
                handleSelectedFile(cameraInput.files[0], cameraInput);
            }
        });
    }

    if (btnUploadPhoto && fileInput) {
        btnUploadPhoto.addEventListener('click', () => {
            clearPhotoError();
            fileInput.click();
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) {
                handleSelectedFile(fileInput.files[0], fileInput);
            }
        });
    }

    // Retake / Change Photo
    if (btnRetakePhoto) {
        btnRetakePhoto.addEventListener('click', () => {
            clearPhotoError();
            // Trigger file picker fallback by default for retake
            if (fileInput) {
                fileInput.click();
            } else if (cameraInput) {
                cameraInput.click();
            }
        });
    }

    // Remove Photo
    if (btnRemovePhoto) {
        btnRemovePhoto.addEventListener('click', () => {
            if (cameraInput) cameraInput.value = '';
            if (fileInput) fileInput.value = '';
            if (photoPreviewImg) photoPreviewImg.src = '';
            if (photoPreviewCard) photoPreviewCard.style.display = 'none';
            if (photoActionButtons) photoActionButtons.style.display = 'grid';
            if (photoHelpText) photoHelpText.style.display = 'block';
            clearPhotoError();
        });
    }

    // -------------------------------------------------------------------------
    // 7. Flash Alerts Auto-Dismissal
    // -------------------------------------------------------------------------
    const alerts = document.querySelectorAll('.flash-alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert && alert.parentElement) {
                alert.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
                alert.style.opacity = '0';
                alert.style.transform = 'translateY(-6px)';
                setTimeout(() => alert.remove(), 400);
            }
        }, 6500);
    });
});
