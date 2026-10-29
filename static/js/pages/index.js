// The landing is rendered on the server (app/landing.py); only the header is added here.
import { nav } from "../ui.js";

document.getElementById("nav").replaceWith(await nav());
