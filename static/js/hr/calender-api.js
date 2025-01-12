// API Configuration
const API_KEY = '4HJ9RWU0qQam2CpxkjPYlWZsnqidPvqP'; // Replace with your API key
const COUNTRY = 'IN'; // Replace with the desired country code (e.g., 'US' for the USA)

// Calendar state
let currentDate = new Date();
let selectedYear = currentDate.getFullYear();
let selectedMonth = currentDate.getMonth();
let selectedDates = []; // Array to store selected dates

// Populate year selector
function populateYearSelector() {
   const yearSelector = document.getElementById("yearSelector");
   const startYear = selectedYear - 5;
   const endYear = selectedYear + 5;

   for (let year = startYear; year <= endYear; year++) {
      const option = document.createElement("option");
      option.value = year;
      option.textContent = year;
      if (year === selectedYear) option.selected = true;
      yearSelector.appendChild(option);
   }
}

// Fetch holidays from API
async function fetchHolidays(year, month) {
   try {
      const response = await fetch(
         `https://calendarific.com/api/v2/holidays?api_key=${API_KEY}&country=${COUNTRY}&year=${year}`
      );
      const data = await response.json();
      return data.response.holidays.filter((holiday) =>
         new Date(holiday.date.iso).getMonth() === month
      );
   } catch (error) {
      console.error("Error fetching holidays:", error);
      return [];
   }
}

// Render calendar
async function renderCalendar() {
   const year = selectedYear;
   const month = selectedMonth;
   const firstDay = new Date(year, month, 1).getDay();
   const daysInMonth = new Date(year, month + 1, 0).getDate();

   const calendarGrid = document.getElementById("calendarGrid");
   const holidayList = document.getElementById("holidayList");
   const currentMonth = document.getElementById("currentMonth");
   
   // Update header
   currentMonth.textContent = new Date(year, month).toLocaleString("default", { month: "long" });
   document.getElementById("yearSelector").value = year;

   // Clear previous data
   calendarGrid.innerHTML = "";
   holidayList.innerHTML = "";

   // Fetch holidays for the month
   const holidays = await fetchHolidays(year, month);

   // Add empty slots for days before the first day
   for (let i = 0; i < firstDay; i++) {
      calendarGrid.innerHTML += `<div class="day empty"></div>`;
   }

   for (let day = 1; day <= daysInMonth; day++) {
      const dayDate = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const holiday = holidays.find((h) => h.date.iso.startsWith(dayDate));
      const isSelected = selectedDates.includes(dayDate); // Check if date is selected
      const selectedDay = new Date(dayDate);
      const isSunday = selectedDay.getDay() === 0; // Check if it's Sunday

      // Apply styles to Sundays (red background)
      const sundayClass = isSunday ? "sunday" : "";
      const holidayClass = holiday && isSunday ? "holiday sunday" : holiday ? "holiday" : "";

      calendarGrid.innerHTML += `
         <div class="day ${holidayClass} ${isSelected ? "selected" : ""} ${sundayClass}" 
            title="${holiday ? holiday.name : ""}" data-date="${dayDate}">
            ${holiday ? '<i class="fas fa-star me-1"></i>' : ""}${day}
         </div>
      `;
   }

   // Add holiday list with star icon
   holidays.forEach((holiday) => {
      const isHolidaySunday = new Date(holiday.date.iso).getDay() === 0; // Check if holiday is on a Sunday
      holidayList.innerHTML += `
         <div class="holiday-item list-group-item ${isHolidaySunday ? 'holiday sunday' : 'holiday'}">
            <i class="fas fa-star me-1 text-warning"></i>
            <strong>${holiday.name}</strong>
            <span class="text-muted">${new Date(holiday.date.iso).toLocaleDateString()}</span>
         </div>
      `;
   });
}

// CSS for Sundays with red background
const style = document.createElement('style');
style.innerHTML = `
   .day.sunday {
      background-color: #d9546c !important;
      color: white;
   }   
`;
document.head.appendChild(style);


// Event listeners for navigation
document.getElementById("prevMonth").addEventListener("click", () => {
   if (selectedMonth === 0) {
      selectedMonth = 11;
      selectedYear--;
   } else {
      selectedMonth--;
   }
   renderCalendar(); // Re-render calendar after month change
});

document.getElementById("nextMonth").addEventListener("click", () => {
   if (selectedMonth === 11) {
      selectedMonth = 0;
      selectedYear++;
   } else {
      selectedMonth++;
   }
   renderCalendar(); // Re-render calendar after month change
});

document.getElementById("yearSelector").addEventListener("change", (event) => {
   selectedYear = parseInt(event.target.value);
   renderCalendar(); // Re-render calendar after year change
});

// Calendar date selection logic
document.getElementById("calendarGrid").addEventListener("click", async (event) => {
   console.log("Calendar clicked");
   if (event.target.classList.contains("day") && !event.target.classList.contains("empty")) {
      const dayDate = event.target.dataset.date;

      // Fetch holidays for the selected month (important to validate holidays in case of month change)
      const holidays = await fetchHolidays(selectedYear, selectedMonth);

      // Check if the selected date is a Sunday (0 represents Sunday in JavaScript's Date object)
      const selectedDay = new Date(dayDate);
      if (selectedDay.getDay() === 0) { // 0 represents Sunday
         alert("Sundays cannot be selected.");
         return; // Prevent selecting Sundays
      }

      // Check if the selected date is a holiday
      if (holidays.some(holiday => holiday.date.iso.startsWith(dayDate))) {
         alert(`The selected date (${dayDate}) is a holiday and cannot be selected.`);
         return; // Prevent selecting holidays
      }

      // Toggle selection for the clicked date
      if (selectedDates.includes(dayDate)) {
         selectedDates = selectedDates.filter((date) => date !== dayDate);
         event.target.classList.remove("selected");
      } else {
         selectedDates.push(dayDate);
         event.target.classList.add("selected");
      }
   }
});

// Submit form and make AJAX POST request
document.querySelector("button[type='submit']").addEventListener("click", async (event) => {
   event.preventDefault(); // Prevent form submission

   const employeeId = document.getElementById("employee_details").value;
   const absenceReason = document.querySelector("textarea[name='absence_reason']").value;

   if (!employeeId || !absenceReason || selectedDates.length === 0) {
      alert("Please fill in all fields and select at least one date.");
      return;
   }

   const formData = {
      employee_id: employeeId,
      reason: absenceReason,
      selected_dates: selectedDates,
   };

   try {
      const response = await fetch('/save/employee/attendance/', {
         method: 'POST',
         headers: {
            'Content-Type': 'application/json',
         },
         body: JSON.stringify(formData),
      });

      if (response.ok) {
         alert("Attendance marked successfully!");
         // You can reset the form or handle success here
      } else {
         alert("There was an error marking attendance.");
      }
   } catch (error) {
      console.error("Error making POST request:", error);
      alert("There was an error. Please try again.");
   }
});

// Initialize
populateYearSelector();
renderCalendar();
