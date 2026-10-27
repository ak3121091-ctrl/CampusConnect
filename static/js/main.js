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
    // 3. Filter Type Tabs (All / Lost / Found)
    // -------------------------------------------------------------------------
    const typeTabs = document.querySelectorAll('.type-tab-btn');
    const itemTypeInput = document.getElementById('itemTypeInput');
    const filterForm = document.getElementById('filterForm');

    if (typeTabs.length > 0 && itemTypeInput && filterForm) {
        typeTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const selectedType = tab.getAttribute('data-type');
                itemTypeInput.value = selectedType;
                filterForm.submit();
            });
        });
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
    // 6. Flash Alerts Auto-Dismissal
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
