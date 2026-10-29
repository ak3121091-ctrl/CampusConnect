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

        if (newType === 'resolved') {
            if (itemTypeInput) itemTypeInput.value = 'all';
            if (statusSelect) statusSelect.value = 'resolved';
        } else if (newType) {
            if (itemTypeInput) itemTypeInput.value = newType;
            if (statusSelect && statusSelect.value === 'resolved') {
                statusSelect.value = 'open';
            }
        }

        // Keep selected tabs visually active and update aria-selected immediately
        const activeType = (newType || (itemTypeInput ? itemTypeInput.value : 'all')) || 'all';
        const activeStatus = (statusSelect ? statusSelect.value : '');
        typeTabs.forEach(t => {
            const tabType = t.getAttribute('data-type');
            let isSelected = false;
            if (tabType === 'resolved') {
                isSelected = (activeStatus === 'resolved' || activeType === 'resolved');
            } else {
                isSelected = (activeStatus !== 'resolved' && activeType !== 'resolved' && tabType === activeType);
            }
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
    const retakeDropdownWrap = document.getElementById('retakeDropdownWrap');
    const retakeOptionsMenu = document.getElementById('retakeOptionsMenu');
    const btnRetakeCamera = document.getElementById('btnRetakeCamera');
    const btnRetakeGallery = document.getElementById('btnRetakeGallery');
    const btnRemovePhoto = document.getElementById('btnRemovePhoto');
    const photoErrorMessage = document.getElementById('photoErrorMessage');

    const MAX_PHOTO_BYTES = 5 * 1024 * 1024; // 5 MB
    const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp'];
    const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/pjpeg', 'image/x-png'];

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

    function openRetakeMenu() {
        if (!retakeOptionsMenu) return;
        retakeOptionsMenu.style.display = 'flex';
        if (btnRetakePhoto) btnRetakePhoto.setAttribute('aria-expanded', 'true');
    }

    function closeRetakeMenu() {
        if (!retakeOptionsMenu) return;
        retakeOptionsMenu.style.display = 'none';
        if (btnRetakePhoto) btnRetakePhoto.setAttribute('aria-expanded', 'false');
    }

    function toggleRetakeMenu() {
        if (!retakeOptionsMenu) return;
        const isOpen = retakeOptionsMenu.style.display === 'flex' || retakeOptionsMenu.style.display === 'block';
        if (isOpen) {
            closeRetakeMenu();
        } else {
            openRetakeMenu();
        }
    }

    function handleSelectedFile(file, activeInput) {
        clearPhotoError();
        if (!file) return;

        // Strict extension & MIME validation (JPEG, PNG, WebP only)
        const ext = (file.name && file.name.lastIndexOf('.') !== -1)
            ? file.name.split('.').pop().toLowerCase().trim()
            : '';
        const mime = file.type ? file.type.toLowerCase().trim() : '';

        const isAllowedExt = ext ? ALLOWED_EXTENSIONS.includes(ext) : false;
        const isAllowedMime = mime ? ALLOWED_MIME_TYPES.includes(mime) : false;

        // Reject if neither matches, or if an invalid extension / MIME is provided
        const isValidFormat = (ext && mime)
            ? (isAllowedExt && isAllowedMime)
            : (isAllowedExt || isAllowedMime);

        if (!isValidFormat) {
            showPhotoError("Unsupported image format. Only JPEG, PNG, and WebP photos are accepted.");
            activeInput.value = '';
            return;
        }

        // File size validation (non-empty and <= 5 MB)
        if (!file.size || file.size <= 0) {
            showPhotoError("Selected photo file is empty (0 bytes). Please select a valid photo.");
            activeInput.value = '';
            return;
        }

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

        // Generate client-side preview with image decoding verification
        const reader = new FileReader();
        reader.onload = function(e) {
            const testImg = new Image();
            testImg.onload = function() {
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
                closeRetakeMenu();
            };
            testImg.onerror = function() {
                showPhotoError("The selected file is corrupt or not a readable image. Please select a valid photo.");
                activeInput.value = '';
            };
            testImg.src = e.target.result;
        };
        reader.onerror = function() {
            showPhotoError("Unable to read selected photo file. Please try another image.");
            activeInput.value = '';
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

    // Retake / Change Photo: Toggle options menu so user can choose camera or files
    if (btnRetakePhoto) {
        btnRetakePhoto.addEventListener('click', (e) => {
            e.stopPropagation();
            clearPhotoError();
            toggleRetakeMenu();
        });
    }

    if (btnRetakeCamera && cameraInput) {
        btnRetakeCamera.addEventListener('click', (e) => {
            e.stopPropagation();
            closeRetakeMenu();
            clearPhotoError();
            cameraInput.click();
        });
    }

    if (btnRetakeGallery && fileInput) {
        btnRetakeGallery.addEventListener('click', (e) => {
            e.stopPropagation();
            closeRetakeMenu();
            clearPhotoError();
            fileInput.click();
        });
    }

    // Close retake menu when clicking outside or pressing Escape
    document.addEventListener('click', (e) => {
        if (retakeDropdownWrap && !retakeDropdownWrap.contains(e.target)) {
            closeRetakeMenu();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeRetakeMenu();
        }
    });

    // Remove Photo: Reset file inputs and restore action buttons
    if (btnRemovePhoto) {
        btnRemovePhoto.addEventListener('click', () => {
            closeRetakeMenu();
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

    // -------------------------------------------------------------------------
    // 8. Authentication UI: Show/Hide Password, Multi-Step Transitions & Validation
    // -------------------------------------------------------------------------
    function setupPasswordToggle(btnId, inputId) {
        const btn = document.getElementById(btnId);
        const input = document.getElementById(inputId);
        if (!btn || !input) return;

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            btn.setAttribute('aria-pressed', isPassword ? 'true' : 'false');
            btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password as plain text');

            const eyeShow = btn.querySelector('.eye-show');
            const eyeHide = btn.querySelector('.eye-hide');
            if (eyeShow && eyeHide) {
                eyeShow.style.display = isPassword ? 'none' : 'inline';
                eyeHide.style.display = isPassword ? 'inline' : 'none';
            }
        });
    }

    setupPasswordToggle('togglePasswordBtn', 'loginPassword');
    setupPasswordToggle('toggleSignupPasswordBtn', 'signupPassword');
    setupPasswordToggle('toggleConfirmPasswordBtn', 'signupConfirmPassword');

    // Google OAuth disabled notice toggler
    document.querySelectorAll('.btn-oauth-disabled').forEach(btn => {
        btn.addEventListener('click', () => {
            const notice = document.getElementById('oauthNotice');
            if (notice) {
                notice.style.display = (notice.style.display === 'none' || !notice.style.display) ? 'block' : 'none';
            }
        });
    });

    // Login Form Submission: Loading state
    const loginForm = document.getElementById('loginForm');
    const btnSubmitLogin = document.getElementById('btnSubmitLogin');
    const loginSpinner = document.getElementById('loginSpinner');
    const loginBtnText = document.getElementById('loginBtnText');
    const loginEmail = document.getElementById('loginEmail');
    const loginPassword = document.getElementById('loginPassword');
    const emailError = document.getElementById('emailError');
    const passwordError = document.getElementById('passwordError');

    if (loginForm && btnSubmitLogin) {
        loginForm.addEventListener('submit', (e) => {
            let isValid = true;
            if (emailError) emailError.style.display = 'none';
            if (passwordError) passwordError.style.display = 'none';

            if (loginEmail && (!loginEmail.value.trim() || !loginEmail.value.includes('@'))) {
                if (emailError) {
                    emailError.textContent = 'Please enter a valid campus email address.';
                    emailError.style.display = 'block';
                }
                isValid = false;
            }

            if (loginPassword && !loginPassword.value) {
                if (passwordError) {
                    passwordError.textContent = 'Please enter your password.';
                    passwordError.style.display = 'block';
                }
                isValid = false;
            }

            if (!isValid) {
                e.preventDefault();
                return;
            }

            btnSubmitLogin.disabled = true;
            if (loginSpinner) loginSpinner.style.display = 'inline-block';
            if (loginBtnText) loginBtnText.textContent = 'Signing in...';
        });
    }

    // Signup Form: Multi-Step Transitions, Password Strength & Confirmation
    const signupForm = document.getElementById('signupForm');
    const stepPanel1 = document.getElementById('stepPanel1');
    const stepPanel2 = document.getElementById('stepPanel2');
    const stepIndicator1 = document.getElementById('stepIndicator1');
    const stepIndicator2 = document.getElementById('stepIndicator2');
    const stepConnector = document.getElementById('stepConnector');
    const btnNextStep = document.getElementById('btnNextStep');
    const btnPrevStep = document.getElementById('btnPrevStep');
    const btnSubmitSignup = document.getElementById('btnSubmitSignup');
    const signupSpinner = document.getElementById('signupSpinner');
    const signupBtnText = document.getElementById('signupBtnText');

    const signupName = document.getElementById('signupName');
    const signupEmail = document.getElementById('signupEmail');
    const signupPassword = document.getElementById('signupPassword');
    const signupConfirmPassword = document.getElementById('signupConfirmPassword');
    const nameError = document.getElementById('nameError');
    const signupEmailError = document.getElementById('emailError');
    const signupPasswordError = document.getElementById('passwordError');
    const confirmPasswordError = document.getElementById('confirmPasswordError');
    const meterFill = document.getElementById('meterFill');
    const meterText = document.getElementById('meterText');
    const matchBadge = document.getElementById('matchBadge');

    function validateStep1() {
        let valid = true;
        if (nameError) nameError.style.display = 'none';
        if (signupEmailError) signupEmailError.style.display = 'none';

        const nameVal = signupName ? signupName.value.trim() : '';
        const rawEmailVal = signupEmail ? signupEmail.value : '';
        const emailVal = rawEmailVal.trim();
        const emailRegex = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;

        if (!nameVal || nameVal.length < 2) {
            if (nameError) {
                nameError.textContent = 'Name must be at least 2 characters long.';
                nameError.style.display = 'block';
            }
            if (signupName) signupName.focus();
            valid = false;
        } else if (!rawEmailVal) {
            if (signupEmailError) {
                signupEmailError.textContent = 'Please enter your campus email address.';
                signupEmailError.style.display = 'block';
            }
            if (signupEmail) signupEmail.focus();
            valid = false;
        } else if (rawEmailVal !== emailVal) {
            if (signupEmailError) {
                signupEmailError.textContent = 'Email address cannot have leading or trailing spaces.';
                signupEmailError.style.display = 'block';
            }
            if (signupEmail) signupEmail.focus();
            valid = false;
        } else if (!emailRegex.test(emailVal) || emailVal.length > 100) {
            if (signupEmailError) {
                signupEmailError.textContent = 'Please enter a valid, properly formatted email address (e.g. student@campus.edu).';
                signupEmailError.style.display = 'block';
            }
            if (signupEmail) signupEmail.focus();
            valid = false;
        }

        return valid;
    }

    if (btnNextStep && stepPanel1 && stepPanel2) {
        btnNextStep.addEventListener('click', () => {
            if (validateStep1()) {
                stepPanel1.style.display = 'none';
                stepPanel2.style.display = 'flex';
                if (stepIndicator1) {
                    stepIndicator1.classList.remove('active');
                    stepIndicator1.classList.add('completed');
                }
                if (stepIndicator2) stepIndicator2.classList.add('active');
                if (stepConnector) stepConnector.classList.add('active');
                if (signupPassword) signupPassword.focus();
            }
        });
    }

    if (btnPrevStep && stepPanel1 && stepPanel2) {
        btnPrevStep.addEventListener('click', () => {
            stepPanel2.style.display = 'none';
            stepPanel1.style.display = 'flex';
            if (stepIndicator1) {
                stepIndicator1.classList.add('active');
                stepIndicator1.classList.remove('completed');
            }
            if (stepIndicator2) stepIndicator2.classList.remove('active');
            if (stepConnector) stepConnector.classList.remove('active');
        });
    }

    function calculatePasswordStrength(pwd) {
        if (!pwd) return { score: 0, label: 'Empty', color: '#64748b', width: '0%' };
        let score = 0;
        if (pwd.length >= 8) score += 1;
        if (pwd.length >= 12) score += 1;
        if (/[a-z]/.test(pwd) && /[A-Z]/.test(pwd)) score += 1;
        if (/[0-9]/.test(pwd)) score += 1;
        if (/[^a-zA-Z0-9]/.test(pwd)) score += 1;

        if (score <= 1) return { score, label: 'Weak (min 8 chars)', color: '#ef4444', width: '25%' };
        if (score === 2) return { score, label: 'Fair', color: '#f59e0b', width: '50%' };
        if (score === 3 || score === 4) return { score, label: 'Good', color: '#3b82f6', width: '75%' };
        return { score, label: 'Strong', color: '#10b981', width: '100%' };
    }

    if (signupPassword && meterFill && meterText) {
        signupPassword.addEventListener('input', () => {
            const pwd = signupPassword.value;
            const strength = calculatePasswordStrength(pwd);
            meterFill.style.width = strength.width;
            meterFill.style.backgroundColor = strength.color;
            meterText.textContent = `Password strength: ${strength.label}`;
            meterText.style.color = strength.color;

            checkPasswordMatch();
        });
    }

    function checkPasswordMatch() {
        if (!signupConfirmPassword || !matchBadge) return;
        const pwd = signupPassword ? signupPassword.value : '';
        const confirmPwd = signupConfirmPassword.value;

        if (!confirmPwd) {
            matchBadge.style.display = 'none';
            return;
        }

        matchBadge.style.display = 'block';
        if (pwd === confirmPwd) {
            matchBadge.textContent = '✓ Passwords match';
            matchBadge.className = 'password-match-badge matched';
        } else {
            matchBadge.textContent = '✗ Passwords do not match';
            matchBadge.className = 'password-match-badge mismatched';
        }
    }

    if (signupConfirmPassword) {
        signupConfirmPassword.addEventListener('input', checkPasswordMatch);
    }

    if (signupForm && btnSubmitSignup) {
        signupForm.addEventListener('submit', (e) => {
            if (signupPasswordError) signupPasswordError.style.display = 'none';
            if (confirmPasswordError) confirmPasswordError.style.display = 'none';

            if (!validateStep1()) {
                e.preventDefault();
                if (btnPrevStep) btnPrevStep.click();
                return;
            }

            const pwd = signupPassword ? signupPassword.value : '';
            const confirmPwd = signupConfirmPassword ? signupConfirmPassword.value : '';

            if (!pwd || pwd.length < 8) {
                e.preventDefault();
                if (signupPasswordError) {
                    signupPasswordError.textContent = 'Password must be at least 8 characters long.';
                    signupPasswordError.style.display = 'block';
                }
                if (signupPassword) signupPassword.focus();
                return;
            }

            if (pwd !== confirmPwd) {
                e.preventDefault();
                if (confirmPasswordError) {
                    confirmPasswordError.textContent = 'Passwords do not match.';
                    confirmPasswordError.style.display = 'block';
                }
                if (signupConfirmPassword) signupConfirmPassword.focus();
                return;
            }

            btnSubmitSignup.disabled = true;
            if (signupSpinner) signupSpinner.style.display = 'inline-block';
            if (signupBtnText) signupBtnText.textContent = 'Creating Account...';
        });
    }

    // -------------------------------------------------------------------------
    // Phase 3: In-App Notification Bell & Dropdown Interactions
    // -------------------------------------------------------------------------
    const navBellBtn = document.getElementById('navBellBtn');
    const navNotificationsDropdown = document.getElementById('navNotificationsDropdown');
    const navNotificationsContainer = document.getElementById('navNotificationsContainer');

    if (navBellBtn && navNotificationsDropdown) {
        navBellBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isExpanded = navBellBtn.getAttribute('aria-expanded') === 'true';
            if (isExpanded) {
                navNotificationsDropdown.hidden = true;
                navBellBtn.setAttribute('aria-expanded', 'false');
            } else {
                navNotificationsDropdown.hidden = false;
                navBellBtn.setAttribute('aria-expanded', 'true');
            }
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (navNotificationsContainer && !navNotificationsContainer.contains(e.target)) {
                navNotificationsDropdown.hidden = true;
                navBellBtn.setAttribute('aria-expanded', 'false');
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !navNotificationsDropdown.hidden) {
                navNotificationsDropdown.hidden = true;
                navBellBtn.setAttribute('aria-expanded', 'false');
                navBellBtn.focus();
            }
        });
    }
});
