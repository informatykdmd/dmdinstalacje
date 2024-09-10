(function($) {
    "use strict";

    /* Wow js init
    -----------------------------*/
    new WOW().init();

    /* Sticky Header
    -----------------------------*/
    $(window).scroll(function() {
        var scroll = $(window).scrollTop();
        if (scroll < 170) {
            $(".header-main-menu").removeClass("sticky");
        } else {
            $(".header-main-menu").addClass("sticky");
        }
    });

    /* Preloader
    -----------------------------*/
    $(window).on('load', function() {
        var preLoder = $("#preloader");
        preLoder.fadeOut(1000);
    });

    /* Back to top
    -----------------------------*/
    $(".back-to-top").on("click", function() {
        $("html,body").animate({
            scrollTop: 0
        }, 2000);
    });

    var lastScrollTop = '';
    $(window).on('scroll', function() {
        var ScrollTop = $('.back-to-top');
        if ($(window).scrollTop() > 1000) {
            ScrollTop.fadeIn(1000);
        } else {
            ScrollTop.fadeOut(1000);
        }
    });

    /* Hero Slider One
    -----------------------------*/
    var $headerCarousel = $('.hero-slider-one');
    if ($headerCarousel.length > 0) {
        $headerCarousel.owlCarousel({
            loop: true,
            autoplay: true,
            autoplayTimeout: 3000,
            autoplayHoverPause: true,
            margin: 0,
            dots: false,
            nav: true,
            mouseover: true,
            navText: ['<i class="fa fa-angle-left"></i>', '<i class="fa fa-angle-right"></i>'],
            animateOut: 'fadeOut',
            animateIn: 'fadeIn',
            responsive: {
                0: {
                    items: 1,
                    nav: false,
                },
                460: {
                    items: 1,
                    nav: false,
                },
                599: {
                    items: 1
                },
                768: {
                    items: 1
                },
                960: {
                    items: 1
                },
                1200: {
                    items: 1
                },
                1920: {
                    items: 1
                }
            }
        });
    }

    /* Client carousel
    -----------------------------*/
    var $ClientCarousel = $('.client-active');
    if ($ClientCarousel.length > 0) {
        $ClientCarousel.owlCarousel({
            loop: true,
            autoplay: true,
            autoPlayTimeout: 1000,
            margin: 30,
            dots: false,
            nav: false,
            navText: ['<i class="fa fa-long-arrow-left"></i>', '<i class="fa fa-long-arrow-right"></i>'],
            animateOut: 'slideInRight',
            animateIn: 'slideOutLeft',
            responsive: {
                0: {
                    items: 2
                },
                460: {
                    items: 3
                },
                599: {
                    items: 4
                },
                768: {
                    items: 4
                },
                960: {
                    items: 5
                },
                1200: {
                    items: 6
                },
                1920: {
                    items: 6
                }
            }
        });
    }

    /* Mobile Menu
    -----------------------------*/
    var clMobileMenu = function() {

        var navWrap = $('.header-nav-wrap'),
            closeNavWrap = navWrap.find('.header-overlay-close'),
            menuToggle = $('.header-toggle-menu'),
            siteBody = $('body');

        menuToggle.on('click', function(e) {
            var $this = $(this);

            e.preventDefault();
            e.stopPropagation();
            siteBody.addClass('nav-wrap-is-visible');
        });

        closeNavWrap.on('click', function(e) {
            var $this = $(this);

            e.preventDefault();
            e.stopPropagation();

            if (siteBody.hasClass('nav-wrap-is-visible')) {
                siteBody.removeClass('nav-wrap-is-visible');
            }
        });

        // open (or close) submenu items in mobile view menu. 
        // close all the other open submenu items.
        $('.header-nav .has-children').children('a').on('click', function(e) {
            e.preventDefault();

            if ($(".close-mobile-menu").is(":visible") == true) {

                $(this).toggleClass('sub-menu-is-open')
                    .next('ul')
                    .slideToggle(200)
                    .end()
                    .parent('.has-children')
                    .siblings('.has-children')
                    .children('a')
                    .removeClass('sub-menu-is-open')
                    .next('ul')
                    .slideUp(200);

            }
        });

    };

    /* Initialize
    -----------------------------*/
    (function ssInit() {

        clMobileMenu();

    })();


})(jQuery);